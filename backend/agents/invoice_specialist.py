"""
Invoice Specialist Agent — handles all invoicing and payment operations.
"""
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

from backend.tools.invoice_tools import (
    ALL_INVOICE_TOOLS,
    list_invoices, get_revenue_summary, get_overdue_invoices,
)
from backend.agents.tool_interceptor import safe_agent_run, _FORMATTERS
from backend.agents.context import append_tool_call
from backend.rag.retriever import ERPRetriever
from backend.agents.prompt_parts import (
    TND_FORMAT_RULE, LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT,
    OUTPUT_TAG_RULE, CONFIRMATION_SYSTEM, RECORD_FORMAT,
)

SYSTEM_PROMPT = f"""You are an Invoicing specialist agent for an IT consulting company.
You ONLY handle invoicing and payment operations: invoices, payments, and revenue reports.

## DOMAIN BOUNDARY:
You handle invoicing only. If the user asks about CRM entities (deals, pipeline stages,
contacts, companies, sales activities), do NOT list deals or contacts. Return exactly:
"This request belongs to the Sales Intelligence module — please try your request again."

## Your tools:
- Query and list invoices by status or client
- Get revenue summaries (get_revenue_summary) — this measures collected revenue (paid invoices), NOT deal pipeline value
- Create invoices with line items (TVA 19% applied automatically)
- Mark invoices as sent or paid

## Rules:
1. READ operations: execute directly and return clear results.
2. WRITE operations: ALWAYS call with confirmed=False first for preview. Wait for explicit user confirmation before calling with confirmed=True.
3. Confirmation keywords: yes, ok, confirm, go ahead, oui, confirme, vas-y, d'accord.
4. {TND_FORMAT_RULE} Always show subtotal, TVA, and total.
5. {LANGUAGE_RULE}
6. Be concise and professional.

{RECORD_FORMAT}

{OUTPUT_TAG_RULE}

{CONFIRMATION_SYSTEM}

{TOOL_CALL_ENFORCEMENT}"""


# ── Write-operation detection ─────────────────────────────────────────────────

_WRITE_KEYWORDS = [
    "create", "make", "add", "new",
    "mark", "send", "cancel", "delete", "update",
    # French
    "créer", "ajouter", "nouveau", "nouvelle",
    "marquer", "envoyer", "supprimer", "annuler",
]

_WRITE_OP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in sorted(_WRITE_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# Two-keyword gate: entity noun + list-intent verb — catches all natural-language
# phrasings without maintaining an exact-phrase list.
_LIST_ENTITY_KW_RE = re.compile(
    r'\b(?:invoices?|factures?|payments?)\b',
    re.IGNORECASE,
)

_LIST_INTENT_VERB_RE = re.compile(
    r'\b(?:list(?:e)?|show|all|every|get|display|afficher|montrer|voir|tous|toutes)\b'
    r'|give\s+me|show\s+me',
    re.IGNORECASE,
)

# Revenue/summary queries don't follow the entity+verb structure
_REVENUE_DIRECT_RE = re.compile(
    r"\b(?:revenue|revenus?|r[ee]sum[ee]\s+des\s+revenus|chiffre\s+d.affaires)\b",
    re.IGNORECASE,
)

# Status-bearing keywords that map directly — bypass the entity+verb gate
_STATUS_KW_RE = re.compile(
    r'\b(?:overdue|paid|draft|sent|cancelled|outstanding|unpaid)\s+invoices?\b'
    r'|\bfactures?\s+(?:en\s+retard|brouillon)\b',
    re.IGNORECASE,
)

# Signals that the message carries a constraint the deterministic path cannot honor:
# time ranges, comparative queries, status/entity filters beyond the _LIST_TOOL_MAP kwargs.
# Any match forces the query through the LLM so parameters are extracted correctly.
_BYPASS_FILTER_GUARD_RE = re.compile(
    # Time constraints (EN + FR)
    r'\b(?:last|this|previous|next|quarter|month|year|week|since|between|'
    r'before|after|today|yesterday)\b'
    r'|\b(?:dernier|derni[eè]re|ce\s+mois|cette\s+ann[ée]e|semaine|trimestre|'
    r'hier|aujourd.hui)\b'
    # Comparative signals
    r'|\b(?:vs\.?|versus|compare[dr]?|comparison|difference|diff[eé]rence)\b'
    r'|\bcompar(?:er|aison)\b'
    # Status filter words the deterministic kwargs don't fully cover
    r'|\b(?:overdue|paid|pending|unpaid)\b'
    # Entity filters: "for [word]", "by [word]"
    r'|\b(?:for|by)\s+\w',
    re.IGNORECASE,
)


# Month name → integer. "may"/"mai" excluded — too ambiguous in natural language.
_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Ordinal quarter names (EN + FR) → quarter number
_NAMED_QUARTER_MAP = [
    (r"first|premier|premi[eè]re",   1),
    (r"second|deuxi[eè]me|2[eè]me",  2),
    (r"third|troisi[eè]me|3[eè]me",  3),
    (r"fourth|quatri[eè]me|4[eè]me", 4),
]


def _extract_time_params(msg_lower: str):
    """
    Return (month, year, quarter) for get_revenue_summary from a natural-language message.
    Any value may be None. Quarter takes precedence over month when both could match.
    """
    from datetime import datetime
    now = datetime.now()
    month, year, quarter = None, None, None

    y = re.search(r'\b(20\d{2})\b', msg_lower)
    if y:
        year = int(y.group(1))

    for name, num in sorted(_MONTH_MAP.items(), key=lambda x: -len(x[0])):
        if re.search(r'\b' + re.escape(name) + r'\b', msg_lower):
            month = num
            break

    if re.search(r'\blast\s+month\b|\bmois\s+dernier\b|\bdernier\s+mois\b', msg_lower):
        month = now.month - 1 if now.month > 1 else 12
        year = year or (now.year if now.month > 1 else now.year - 1)
        return month, year, None

    if re.search(r'\bthis\s+month\b|\bce\s+mois\b', msg_lower):
        return now.month, year or now.year, None

    if re.search(r'\bthis\s+year\b|\bcette\s+ann[ée]e\b', msg_lower):
        return None, year or now.year, None

    if re.search(r'\blast\s+year\b|\bann[ée]e\s+derni[eè]re\b|\bl.ann[ée]e\s+derni[eè]re\b', msg_lower):
        return None, year or (now.year - 1), None

    # Named ordinal quarters: "first quarter", "deuxième trimestre", etc.
    for pattern, num in _NAMED_QUARTER_MAP:
        if re.search(r'\b(?:' + pattern + r')\s+(?:quarter|trimestre)\b', msg_lower):
            return None, year, num

    # Explicit quarter: "Q1", "Q2", "Q3", "Q4"
    qm = re.search(r'\bq([1-4])\b', msg_lower)
    if qm:
        return None, year, int(qm.group(1))

    # "last quarter" / "previous quarter" / "dernier trimestre" — compute relative to now
    if re.search(r'\b(?:last|previous|dernier)\s+quarter\b|\btrimestre\s+(?:dernier|précédent)\b', msg_lower):
        cur_q = (now.month - 1) // 3 + 1
        last_q = cur_q - 1 if cur_q > 1 else 4
        ref_year = now.year if cur_q > 1 else now.year - 1
        return None, year or ref_year, last_q

    return month, year, quarter


_LIST_TOOL_MAP = [
    # Overdue — dedicated tool, raw output (header + space-indented rows,
    # no [id] prefix — _fmt_invoices would garble it)
    ("factures en retard",     get_overdue_invoices,  {},                       None),
    ("overdue",                get_overdue_invoices,  {},                       None),
    # Status-filtered — specific before generic
    ("paid invoices",          list_invoices,         {"status": "paid"},       "list_invoices"),
    ("factures payees",        list_invoices,         {"status": "paid"},       "list_invoices"),
    ("draft invoices",         list_invoices,         {"status": "draft"},      "list_invoices"),
    ("factures brouillon",     list_invoices,         {"status": "draft"},      "list_invoices"),
    ("sent invoices",          list_invoices,         {"status": "sent"},       "list_invoices"),
    ("factures envoyees",      list_invoices,         {"status": "sent"},       "list_invoices"),
    ("cancelled invoices",     list_invoices,         {"status": "cancelled"},  "list_invoices"),
    ("factures annulees",      list_invoices,         {"status": "cancelled"},  "list_invoices"),
    ("unpaid invoices",        list_invoices,         {"status": "sent"},       "list_invoices"),
    ("outstanding invoices",   list_invoices,         {"status": "sent"},       "list_invoices"),
    ("factures impayees",      list_invoices,         {"status": "sent"},       "list_invoices"),
    # Payments → paid invoices (closest available mapping)
    ("payments",               list_invoices,         {"status": "paid"},       "list_invoices"),
    # Generic — last resort
    ("factures",               list_invoices,         {},                       "list_invoices"),
    ("invoices",               list_invoices,         {},                       "list_invoices"),
]


def _is_invoice_write_operation(message: str) -> bool:
    return bool(_WRITE_OP_RE.search(message))


def _is_list_intent(message: str) -> bool:
    msg_lower = message.lower().strip()
    return (
        bool(_STATUS_KW_RE.search(msg_lower))
        or bool(_REVENUE_DIRECT_RE.search(msg_lower))
        or (bool(_LIST_ENTITY_KW_RE.search(msg_lower)) and bool(_LIST_INTENT_VERB_RE.search(msg_lower)))
    )


def _last_warning_in_history(history: Optional[List[Dict]]) -> Optional[str]:
    """
    Return WARNING content only if the most recent assistant turn is a WARNING.
    Stops immediately at the first assistant message — does not scan stale history.
    """
    for msg in reversed(history or []):
        if msg.get("role") == "assistant":
            content = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            if re.match(r"^warning[!:\s]", content, re.IGNORECASE):
                return content
            return None  # Most recent assistant turn is not a WARNING — stop
    return None


# ── Agent caching (daily refresh to keep date current) ───────────────────────

_invoice_agent_instance: Optional[AgentExecutor] = None
_invoice_agent_date: Optional[str] = None


def _get_invoice_agent() -> AgentExecutor:
    global _invoice_agent_instance, _invoice_agent_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _invoice_agent_instance is None or _invoice_agent_date != today:
        _invoice_agent_instance = create_invoice_agent()
        _invoice_agent_date = today
    return _invoice_agent_instance


def extract_company_from_message(
    message: str, history: Optional[List[Dict]]
) -> Optional[str]:
    """
    Return the most specific matching company name found in the message, or None.
    Sorts by name length descending so 'Acme Corporation' beats 'Acme'.
    Uses word boundaries to avoid false substring matches.
    """
    from backend.models.database import get_session
    from backend.models.crm_models import Company
    db = get_session()
    try:
        companies = db.query(Company.name).filter(Company.is_deleted == False).all()
        message_lower = message.lower()
        names = sorted([name for (name,) in companies], key=len, reverse=True)
        for name in names:
            pattern = r'\b' + re.escape(name.lower()) + r'\b'
            if re.search(pattern, message_lower):
                return name
        return None
    finally:
        db.close()


def create_invoice_agent() -> AgentExecutor:
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm=llm, tools=ALL_INVOICE_TOOLS, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=ALL_INVOICE_TOOLS,
        verbose=True,
        max_iterations=15,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


def run_invoice_agent(message: str, history: List[Dict] = None) -> str:
    agent = _get_invoice_agent()

    lc_history = []
    for msg in (history or []):
        if msg.get("role") == "human":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            clean = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            lc_history.append(AIMessage(content=clean))

    # Skip RAG for write operations, active WARNING confirmations, and generic
    # list intents — RAG context biases the model toward whichever entities
    # happen to be nearest in the index, causing implicit company filters.
    if _is_invoice_write_operation(message) or _last_warning_in_history(history):
        return safe_agent_run(agent, ALL_INVOICE_TOOLS, message, lc_history)

    if _is_list_intent(message):
        msg_lower = message.lower().strip()
        # Revenue queries: always deterministic, time params extracted directly.
        # Never routes to the LLM, which would wrap the tool output in prose.
        if _REVENUE_DIRECT_RE.search(msg_lower):
            month, year, quarter = _extract_time_params(msg_lower)
            rev_kwargs = {k: v for k, v in [("month", month), ("year", year), ("quarter", quarter)] if v is not None}
            t0 = time.monotonic()
            raw = str(get_revenue_summary.invoke(rev_kwargs))
            log_tool_call(logger, "get_revenue_summary", rev_kwargs, raw, (time.monotonic() - t0) * 1000)
            append_tool_call({"tool": "get_revenue_summary", "params": rev_kwargs, "source": "deterministic_bypass"})
            return _FORMATTERS["get_revenue_summary"](raw)
        has_entity_filter = bool(re.search(r'\b(?:for|by)\s+[A-Za-z]', msg_lower))
        has_filter_constraint = bool(_BYPASS_FILTER_GUARD_RE.search(msg_lower))
        if not has_filter_constraint:
            for keyword, tool_fn, kwargs, formatter_key in _LIST_TOOL_MAP:
                if keyword in msg_lower:
                    t0 = time.monotonic()
                    raw = str(tool_fn.invoke(kwargs))
                    log_tool_call(logger, tool_fn.name, kwargs, raw, (time.monotonic() - t0) * 1000)
                    append_tool_call({"tool": tool_fn.name, "params": kwargs, "source": "deterministic_bypass"})
                    return _FORMATTERS[formatter_key](raw) if formatter_key else raw
        elif has_filter_constraint and not has_entity_filter:
            matched, seen = [], set()
            for keyword, tool_fn, kwargs, formatter_key in _LIST_TOOL_MAP:
                if keyword in msg_lower:
                    cache_key = (tool_fn.name, frozenset(kwargs.items()))
                    if cache_key not in seen:
                        seen.add(cache_key)
                        t0 = time.monotonic()
                        raw = str(tool_fn.invoke(kwargs))
                        log_tool_call(logger, tool_fn.name, kwargs, raw, (time.monotonic() - t0) * 1000)
                        append_tool_call({"tool": tool_fn.name, "params": kwargs, "source": "deterministic_bypass"})
                        matched.append(_FORMATTERS[formatter_key](raw) if formatter_key else raw)
            if len(matched) >= 2:
                return "\n\n".join(matched)
        return safe_agent_run(agent, ALL_INVOICE_TOOLS, message, lc_history, is_list_query=True)

    # Specific-entity read operations: inject RAG context
    retriever = ERPRetriever(module="invoicing", top_k=5)
    docs = retriever.retrieve(message)
    context = retriever.format_context(docs)

    company_name = extract_company_from_message(message, history)
    if company_name:
        company_docs = retriever.retrieve_for_company(company_name, message)
        company_context = retriever.format_context(company_docs)
        context = company_context + "\n\n" + context

    try:
        from backend.agents.context import set_rag_context
        set_rag_context(context)
    except Exception:
        pass

    enriched_message = (
        f"RELEVANT CONTEXT FROM AXIS KNOWLEDGE BASE:\n"
        f"{context}\n\n"
        f"USER REQUEST:\n"
        f"{message}"
    )

    return safe_agent_run(agent, ALL_INVOICE_TOOLS, enriched_message, lc_history)
