"""Chart Generation Agent — creates Plotly charts from ERP warehouse data."""
import re
import time
import logging
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from backend.agents.llm import get_llm
from langchain_core.messages import HumanMessage, AIMessage
from typing import List, Dict, Optional
from datetime import datetime
from logging_config import log_tool_call

logger = logging.getLogger(__name__)

from backend.tools.chart_tools import (
    ALL_CHART_TOOLS,
    generate_churn_risk_chart,
    generate_deal_prediction_chart,
)
from backend.agents.tool_interceptor import safe_agent_run
from backend.agents.prompt_parts import (
    LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT, OUTPUT_TAG_RULE, CONFIRMATION_SYSTEM,
)

# Fix 2 — complexity guard
_TEMPORAL_KEYWORDS = [
    "monthly", "by month", "par mois", "weekly", "by week", "par semaine",
    "daily", "by day", "par jour", "by year", "by quarter", "over time",
    "trend", "time series", "evolution", "évolution", "par trimestre",
    "annuel", "mensuel", "hebdomadaire",
]
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

# Fix 1 — fabrication guard
_FABRICATION_PATTERNS = ["created successfully", "chart id"]
_CHART_FABRICATION_MSG = (
    "⚠️ The chart agent did not call any tools for this request — it may have "
    "fabricated a response. Please rephrase your request or try: "
    "\"create a bar chart of deal count by stage from fact_deals\"."
)

SYSTEM_PROMPT = f"""You are the AXIS Chart Generation Agent. You help users create custom data
visualizations from the ERP warehouse data. When a user requests a chart, extract:
chart_type, x_column, y_column, data_source, title, and any filters.
Always confirm what chart you are creating before generating it.

Available data sources:
- fact_deals: deal_ref, company_name, title, stage, status, value_tnd, probability,
  deal_size_category, quarter, days_to_close, created_date, closed_date
- fact_revenue: invoice_number, company_name, invoice_date, due_date, subtotal,
  tax_amount, total_amount, amount_paid, status, payment_delay_days, is_overdue,
  days_outstanding
- fact_activities: source_id, company_name, activity_type, activity_date,
  duration_min, outcome, churn_signal, positive_signal
- dim_client: company_name, industry, city, country, status, first_deal_date,
  total_won_deals, total_revenue

Available chart types: bar, line, scatter, pie, donut, funnel, area

For y_column: if user says 'count' or 'number of', use 'count'.
For aggregation: use 'sum' for values/amounts, 'count' for quantities, 'avg' for averages.

Rules:
1. Always call generate_chart with all required parameters.
2. Use descriptive, human-readable titles.
3. For ANY request about listing, showing, or viewing saved charts,
   you MUST call list_saved_charts() tool immediately. Never answer
   from memory. Always call the tool.
4. For delete requests, use confirmed=False first, then confirmed=True after user confirms.
5. {LANGUAGE_RULE}
6. Be concise and confirm chart creation with the chart ID.

{OUTPUT_TAG_RULE}

CRITICAL: For list/show/view chart requests → call list_saved_charts() NOW.
For delete requests → call delete_chart() with confirmed=False first.
For create requests → call generate_chart() with all parameters.
You MUST use tools. Never describe what you would do. Just do it.

{CONFIRMATION_SYSTEM}

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

# Compiled once — extract "top N" and "above/below X%"
_TOP_N_RE = re.compile(r'top\s*(\d+)', re.IGNORECASE)
_THRESHOLD_RE = re.compile(
    r'(above|below|over|under|greater|less)\s+(\d+(?:\.\d+)?)\s*%',
    re.IGNORECASE,
)

# Signal words that indicate a churn-chart vs deal-chart intent
_CHURN_SIGNALS = {"churn", "churn risk", "at risk clients", "clients above", "clients below"}
_DEAL_SIGNALS  = {"win probability", "deal prediction", "pipeline forecast",
                  "deals above", "deals below", "win chance", "deal outcome"}

# Chart type words in order of specificity
_CHART_TYPE_MAP = [
    ("donut",     "pie"),
    ("pie",       "pie"),
    ("scatter",   "scatter"),
    ("histogram", "histogram"),
    ("bar",       "bar"),
    ("line",      "line"),
]

# Broader co-occurrence signals: churn intent = any churn word + any action word
_CHURN_WORDS  = {"churn", "retention", "at-risk", "at risk"}
_DEAL_WORDS   = {"deal", "deals", "win", "pipeline", "opportunity", "opportunities"}
_ACTION_WORDS = {"chart", "top", "above", "below", "predict", "show", "probability",
                 "percentage", "histogram", "scatter", "pie", "bar"}


def _extract_chart_type(message: str) -> str:
    msg_lower = message.lower()
    for word, ct in _CHART_TYPE_MAP:
        if word in msg_lower:
            return ct
    return "bar"


def _extract_prediction_params(message: str) -> dict:
    """Extract top_n and min/max_probability from natural-language message."""
    params: dict = {}

    m = _TOP_N_RE.search(message)
    if m:
        params["top_n"] = int(m.group(1))

    m = _THRESHOLD_RE.search(message)
    if m:
        direction, value = m.group(1).lower(), float(m.group(2)) / 100
        if direction in {"above", "over", "greater"}:
            params["min_probability"] = value
        else:
            params["max_probability"] = value

    return params


def _is_churn_chart_intent(msg_lower: str) -> bool:
    """True when the message is asking for a churn prediction chart."""
    # Exact phrases
    if any(phrase in msg_lower for phrase in _CHURN_SIGNALS):
        return True
    # Co-occurrence: any churn word + any action/chart word
    has_churn  = any(w in msg_lower for w in _CHURN_WORDS)
    has_action = any(w in msg_lower for w in _ACTION_WORDS)
    return has_churn and has_action


def _is_deal_chart_intent(msg_lower: str) -> bool:
    """True when the message is asking for a deal-win prediction chart."""
    # Exact phrases
    if any(phrase in msg_lower for phrase in _DEAL_SIGNALS):
        return True
    # Co-occurrence: any deal word + any action/chart word
    has_deal   = any(w in msg_lower for w in _DEAL_WORDS)
    has_action = any(w in msg_lower for w in _ACTION_WORDS)
    return has_deal and has_action


def _is_list_intent(message: str) -> bool:
    msg_lower = message.lower().strip()
    return any(intent in msg_lower for intent in _LIST_INTENTS)


def run_chart_agent(message: str, history: List[Dict] = None) -> str:
    # Fix 2 — complexity guard (before any LLM call)
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in _TEMPORAL_KEYWORDS):
        return _UNSUPPORTED_COMPLEXITY_MSG
    if _MULTI_FILTER_RE.search(message):
        return _UNSUPPORTED_COMPLEXITY_MSG

    # Predictive chart bypass — deterministic, no LLM needed.
    # Churn checked before deal because "at risk clients" overlaps with deal words.
    chart_type = _extract_chart_type(message)
    if _is_churn_chart_intent(msg_lower):
        invoke_args = {"chart_type": chart_type, **_extract_prediction_params(message)}
        t0 = time.monotonic()
        result = generate_churn_risk_chart.invoke(invoke_args)
        log_tool_call(logger, "generate_churn_risk_chart", invoke_args, result, (time.monotonic() - t0) * 1000)
        return result
    if _is_deal_chart_intent(msg_lower):
        invoke_args = {"chart_type": chart_type, **_extract_prediction_params(message)}
        t0 = time.monotonic()
        result = generate_deal_prediction_chart.invoke(invoke_args)
        log_tool_call(logger, "generate_deal_prediction_chart", invoke_args, result, (time.monotonic() - t0) * 1000)
        return result

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

    # Fix 1 — fabrication guard: invoke directly to inspect intermediate_steps
    try:
        result = agent.invoke({
            "input": message,
            "chat_history": lc_history,
        })
        response = result.get("output", "")
        steps = result.get("intermediate_steps", [])
        resp_lower = response.lower()
        if not steps and any(pat in resp_lower for pat in _FABRICATION_PATTERNS):
            return _CHART_FABRICATION_MSG
        return response
    except Exception:
        logger.error("Chart agent direct invoke failed, falling back to safe_agent_run", exc_info=True)
        return safe_agent_run(agent, ALL_CHART_TOOLS, message, lc_history)
