"""Chart Generation Agent — creates Plotly charts from AXIS warehouse data."""
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
from backend.agents.tool_interceptor import safe_agent_run, _extract_tool_call, _find_tool
from backend.agents.prompt_parts import (
    LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT, OUTPUT_TAG_RULE,
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
AXIS warehouse data. Your only tools are generate_chart, list_saved_charts, and delete_chart.

## TOOL USE IS MANDATORY: For every chart request, you MUST invoke generate_chart. Do not produce a textual response describing chart creation without first calling the tool. The tool is the only mechanism that creates charts; without a tool call, no chart exists. Failure to call the tool will cause the user's request to fail.

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

## Multiple filters (status + year, or any two conditions):
Use filter_column/filter_value for the first condition and filter_column2/filter_value2 for the second.
Year values (4-digit numbers) on date columns are handled automatically — pass them as a string.
Example — "bar chart of won deals in 2024 by stage":
  data_source=fact_deals, x_column=stage, y_column=count, aggregation=count, chart_type=bar,
  filter_column=status, filter_value=won, filter_column2=created_date, filter_value2=2024

Example — "line chart of paid invoices by month in 2025":
  data_source=fact_revenue, x_column=invoice_date, x_truncation=month, y_column=total_amount,
  aggregation=sum, chart_type=line, filter_column=status, filter_value=paid,
  filter_column2=invoice_date, filter_value2=2025

Example — "bar chart of lost deals by company in 2024":
  data_source=fact_deals, x_column=company_name, y_column=count, aggregation=count, chart_type=bar,
  filter_column=status, filter_value=lost, filter_column2=closed_date, filter_value2=2024

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


def _try_intercept_raw_call(response: str) -> Optional[str]:
    """If response is a raw JSON tool-call, execute the tool and return its output.
    Returns None if no valid tool-call JSON is found."""
    if not response:
        return None
    raw_call = _extract_tool_call(response)
    if not (raw_call and "name" in raw_call):
        return None
    params = raw_call.get("parameters") or raw_call.get("arguments") or {}
    tool = _find_tool(raw_call["name"], ALL_CHART_TOOLS)
    if tool is None:
        return None
    logger.warning(f"[Chart] Raw tool call intercepted: {raw_call['name']} — executing")
    try:
        return str(tool.invoke(params))
    except Exception as te:
        logger.error(f"[Chart] Intercepted tool execution failed: {te}", exc_info=True)
        return None


def run_chart_agent(message: str, history: List[Dict] = None) -> str:
    agent = _get_chart_agent()
    lc_history = []
    for msg in (history or []):
        if msg.get("role") == "human":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            clean = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            lc_history.append(AIMessage(content=clean))

    if _is_list_intent(message):
        return safe_agent_run(agent, ALL_CHART_TOOLS, message, lc_history, is_list_query=True)

    response = ""
    steps = []
    try:
        result = agent.invoke({"input": message, "chat_history": lc_history})
        response = result.get("output", "")
        steps = result.get("intermediate_steps", [])
    except Exception:
        logger.error("Chart agent direct invoke failed, falling back to safe_agent_run", exc_info=True)
        return safe_agent_run(agent, ALL_CHART_TOOLS, message, lc_history)

    # ── No tool was called — attempt recovery ────────────────────────────────
    if not steps:
        # Pass 1: output may be raw JSON tool-call (Qwen sometimes does this)
        intercepted = _try_intercept_raw_call(response)
        if intercepted is not None:
            return intercepted

        # Pass 2: retry with an explicit tool-forcing directive
        logger.warning("[Chart] No tool called on first attempt — retrying with directive")
        forced = (
            "CRITICAL: You did not call any tool. You MUST call generate_chart now. "
            "Do NOT write a text response — invoke the tool with the correct parameters. "
            f"Original request: {message}"
        )
        try:
            retry_result = agent.invoke({"input": forced, "chat_history": lc_history})
            retry_response = retry_result.get("output", "")
            retry_steps = retry_result.get("intermediate_steps", [])
            if retry_steps:
                # Tool was called on retry — check fabrication then return
                if _is_fabricated(retry_response, retry_steps):
                    return _CHART_FABRICATION_MSG
                return retry_response
            # Retry also produced no steps — check for raw JSON one more time
            intercepted2 = _try_intercept_raw_call(retry_response)
            if intercepted2 is not None:
                return intercepted2
        except Exception:
            logger.error("Chart retry invoke failed", exc_info=True)

        return _CHART_FABRICATION_MSG

    # ── Tool was called — belt-and-suspenders fabrication check ──────────────
    if _is_fabricated(response, steps):
        return _CHART_FABRICATION_MSG
    return response
