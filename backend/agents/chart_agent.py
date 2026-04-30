"""Chart Generation Agent — creates Plotly charts from ERP warehouse data."""
import re
import logging
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from backend.agents.llm import get_llm
from langchain_core.messages import HumanMessage, AIMessage
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from backend.tools.chart_tools import ALL_CHART_TOOLS
from backend.agents.tool_interceptor import safe_agent_run
from backend.agents.prompt_parts import (
    LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT, OUTPUT_TAG_RULE,
)

_MULTI_FILTER_RE = re.compile(
    r"(?:won|lost|open|closed|paid|overdue|pending|active|cancelled)"
    r".*?\b(20\d{2})\b"
    r"|"
    r"\b(20\d{2})\b.*?(?:won|lost|open|closed|paid|overdue|pending|active|cancelled)",
    re.IGNORECASE,
)
_UNSUPPORTED_COMPLEXITY_MSG = (
    "⚠️ This chart request requires time-series aggregation or combined "
    "status+year filtering, which goes beyond what the chart engine supports "
    "directly. Try a simpler query — for example:\n"
    "• \"create a bar chart of deal count by stage from fact_deals\"\n"
    "• \"show total revenue by company as a pie chart\"\n"
    "• \"create a funnel chart of deal stages\""
)

_FABRICATION_SUBSTRINGS = [
    # English — exact tool return phrasing
    "created successfully",
    "chart id",
    # English — alternate phrasings
    "chart created",
    "chart was created",
    "chart identifier",
    # French
    "identifiant",
    "a été créé",   # "a été créé"
    "créé avec succès",   # "créé avec succès"
]
# Matches "the chart" within 30 chars of a bare integer (e.g. "The chart (ID 7) is ready")
_FABRICATION_CHART_ID_RE = re.compile(r"the chart.{0,30}\d+", re.IGNORECASE)

_CHART_FABRICATION_MSG = (
    "⚠️ The chart agent did not call any tools for this request — it may have "
    "fabricated a response. Please rephrase your request or try: "
    "\"create a bar chart of deal count by stage from fact_deals\"."
)


def _is_fabricated(response: str, steps: list) -> bool:
    if steps:
        return False
    resp_lower = response.lower()
    if any(pat in resp_lower for pat in _FABRICATION_SUBSTRINGS):
        return True
    if _FABRICATION_CHART_ID_RE.search(response):
        return True
    return False

SYSTEM_PROMPT = f"""You are the AXIS Chart Generation Agent. You create Plotly charts from
ERP warehouse data. Your only tools are generate_chart, list_saved_charts, and delete_chart.

## TOOL USE IS MANDATORY: For every chart request, you MUST invoke generate_chart. Do not produce a textual response describing chart creation without first calling the tool. The tool is the only mechanism that creates charts; without a tool call, no chart exists. Failure to call the tool will cause the user's request to fail.

## PREDICTION / RISK CHARTS:
If the user asks for a churn chart, prediction chart, risk chart, win probability chart,
or any ML-based chart, respond with exactly:
"Predictive analytics charts are available in the Power BI dashboards, not the conversational interface."
Do NOT call generate_chart for these requests.

## Available data sources and their columns:
- fact_deals: deal_ref, company_name, title, stage, status, value_tnd, probability,
  deal_size_category, quarter, days_to_close, created_date, closed_date
- fact_revenue: invoice_number, company_name, invoice_date, due_date, subtotal,
  tax_amount, total_amount, amount_paid, status, payment_delay_days, is_overdue,
  days_outstanding
- fact_activities: source_id, company_name, activity_type, activity_date,
  duration_min, outcome, churn_signal, positive_signal
- dim_client: company_name, industry, city, country, status, first_deal_date,
  total_won_deals, total_revenue

## Available chart types: bar, line, scatter, pie, donut, funnel, area

## Parameter mapping rules:
- y_column: use 'count' when the user says 'count', 'number of', or 'how many'.
- aggregation: 'sum' for revenue/value totals, 'count' for quantities, 'avg' for averages.

## Axis interpretation:
- Explicit axes ("x-axis: stage, y-axis: count"): pass them directly as x_column and y_column.
- Implicit phrasing ("deals by stage", "revenue by company"): the term AFTER 'by' is the
  x-axis (x_column); the term BEFORE 'by' is the y-axis (y_column / aggregated metric).
  Example: "deals by stage" → x_column=stage, y_column=count, data_source=fact_deals.
  Example: "revenue by company" → x_column=company_name, y_column=total_amount, data_source=fact_revenue.

## Time-series charts ("by month", "by quarter", "by year", etc.):
REQUIRED: whenever the user says 'by month', 'by quarter', 'by year', 'by week', or 'by day',
you MUST set x_truncation to the matching period (month / quarter / year / week / day).
Without x_truncation, date columns are not truncated and produce one point per invoice date —
this breaks the line and creates a zigzag. Always set x_truncation for date dimensions.
- x_column: the date column (invoice_date, created_date, closed_date, activity_date)
- x_truncation: month | year | quarter | week | day
- chart_type: 'line' or 'area' for trends, 'bar' for period comparisons
Example — "line chart of revenue by month":
  data_source=fact_revenue, x_column=invoice_date, x_truncation=month,
  y_column=total_amount, aggregation=sum, chart_type=line

Example — "area chart of revenue by month":
  data_source=fact_revenue, x_column=invoice_date, x_truncation=month,
  y_column=total_amount, aggregation=sum, chart_type=area

## Pie and donut charts:
Pie/donut: x_column is the categorical dimension (labels), y_column is 'count' or the numeric column being aggregated.
Example — "pie chart of deals by status":
  data_source=fact_deals, x_column=status, y_column=count, aggregation=count, chart_type=pie
Example — "donut chart of clients by industry":
  data_source=dim_client, x_column=industry, y_column=count, aggregation=count, chart_type=donut

## Scatter charts:
Scatter shows raw data points — two numeric columns, NO aggregation needed (aggregation defaults to 'sum' but has no effect when each row is a point). Do NOT set aggregation for scatter.
Example — "scatter chart of deal value vs days to close":
  data_source=fact_deals, x_column=value_tnd, y_column=days_to_close, chart_type=scatter

## Funnel charts:
Funnel: x_column is the stage/category dimension, y_column is 'count' or a numeric metric.
Example — "funnel chart of deal stages":
  data_source=fact_deals, x_column=stage, y_column=count, aggregation=count, chart_type=funnel

## Listing saved charts:
When the user says "list my charts", "show my charts", "show saved charts", "what charts do I have",
"list saved charts", or any equivalent phrasing — call list_saved_charts() with NO parameters.
Do NOT fabricate a list. The tool queries the database and returns the real saved charts.
Example — "list my saved charts":
  call list_saved_charts()

## Rules:
1. Always call generate_chart with all required parameters.
2. Use descriptive, human-readable titles.
3. For list/show/view chart requests → call list_saved_charts() with no parameters immediately. NEVER describe or fabricate the list — call the tool.
4. For delete requests → call delete_chart() with confirmed=False first.
5. {LANGUAGE_RULE}
6. After generate_chart returns, relay its output verbatim. Do NOT pre-write or paraphrase a 'chart created' message before the tool returns — the tool itself produces the success string.

{OUTPUT_TAG_RULE}

You MUST use tools. Never describe what you would do — just do it.

{TOOL_CALL_ENFORCEMENT}"""


_chart_agent_instance: Optional[AgentExecutor] = None
_chart_agent_date: Optional[str] = None


def _get_chart_agent() -> AgentExecutor:
    global _chart_agent_instance, _chart_agent_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _chart_agent_instance is None or _chart_agent_date != today:
        _chart_agent_instance = create_chart_agent()
        _chart_agent_date = today
    return _chart_agent_instance


def create_chart_agent() -> AgentExecutor:
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm=llm, tools=ALL_CHART_TOOLS, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=ALL_CHART_TOOLS,
        verbose=True,
        max_iterations=10,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


_LIST_INTENTS = [
    "list charts", "show charts", "all charts", "my charts",
    "list saved charts", "show saved charts", "show my saved charts",
    "liste des graphiques", "afficher graphiques",
]


def _is_list_intent(message: str) -> bool:
    msg_lower = message.lower().strip()
    return any(intent in msg_lower for intent in _LIST_INTENTS)


def run_chart_agent(message: str, history: List[Dict] = None) -> str:
    if _MULTI_FILTER_RE.search(message):
        return _UNSUPPORTED_COMPLEXITY_MSG

    agent = _get_chart_agent()
    lc_history = []
    for msg in (history or []):
        if msg.get("role") == "human":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            clean = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            lc_history.append(AIMessage(content=clean))

    # No RAG in chart agent — LIST_INTENTS guard here is solely for formatter routing
    if _is_list_intent(message):
        return safe_agent_run(agent, ALL_CHART_TOOLS, message, lc_history, is_list_query=True)

    # Invoke directly so we can inspect intermediate_steps for the fabrication guard.
    # The guard runs AFTER both the primary path and the fallback path so neither can bypass it.
    response = ""
    steps = []
    try:
        result = agent.invoke({
            "input": message,
            "chat_history": lc_history,
        })
        response = result.get("output", "")
        steps = result.get("intermediate_steps", [])
    except Exception:
        logger.error("Chart agent direct invoke failed, falling back to safe_agent_run", exc_info=True)
        response = safe_agent_run(agent, ALL_CHART_TOOLS, message, lc_history)
        # safe_agent_run has no intermediate_steps; steps stays [] so guard still applies.

    if _is_fabricated(response, steps):
        return _CHART_FABRICATION_MSG
    return response
