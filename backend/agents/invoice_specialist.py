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
from backend.rag.retriever import ERPRetriever
from backend.agents.prompt_parts import (
    TND_FORMAT_RULE, LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT,
    OUTPUT_TAG_RULE, CONFIRMATION_SYSTEM, RECORD_FORMAT,
)

SYSTEM_PROMPT = f"""You are an Invoicing specialist agent for an IT consulting company.
You ONLY handle invoicing and payment operations: invoices, payments, and revenue reports.

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


_LIST_INTENTS = [
    # Generic invoice lists
    "list invoices", "show invoices", "all invoices", "get invoices",
    "list all invoices", "show all invoices",
    # Status-filtered invoice lists
    "list paid invoices", "paid invoices", "show paid invoices",
    "list overdue invoices", "overdue invoices", "show overdue invoices", "overdue",
    "list draft invoices", "draft invoices", "show draft invoices",
    "list sent invoices", "sent invoices", "show sent invoices",
    "list cancelled invoices", "cancelled invoices",
    "unpaid invoices", "outstanding invoices",
    # Payments
    "list payments", "show payments",
    # Revenue / summary queries
    "revenue", "monthly revenue", "revenue summary", "total revenue",
    "revenus", "revenus mensuels", "resume des revenus", "chiffre d'affaires",
    "total des revenus", "résumé des revenus",
    # French invoice lists
    "liste des factures", "afficher factures", "afficher les factures",
    "toutes les factures", "factures payees", "factures impayees",
    "factures en retard", "factures brouillon", "factures envoyees",
    "factures annulees",
]


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
    # Revenue / summary — _fmt_revenue_summary is a pass-through
    ("chiffre d'affaires",     get_revenue_summary,   {},                       "get_revenue_summary"),
    ("revenus",                get_revenue_summary,   {},                       "get_revenue_summary"),
    ("revenue",                get_revenue_summary,   {},                       "get_revenue_summary"),
    # Generic — last resort
    ("factures",               list_invoices,         {},                       "list_invoices"),
    ("invoices",               list_invoices,         {},                       "list_invoices"),
]


def _is_invoice_write_operation(message: str) -> bool:
    return bool(_WRITE_OP_RE.search(message))


def _is_list_intent(message: str) -> bool:
    msg_lower = message.lower().strip()
    return any(intent in msg_lower for intent in _LIST_INTENTS)


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
        if len(message.split()) <= 4:
            msg_lower = message.lower().strip()
            for keyword, tool_fn, kwargs, formatter_key in _LIST_TOOL_MAP:
                if keyword in msg_lower:
                    t0 = time.monotonic()
                    raw = str(tool_fn.invoke(kwargs))
                    log_tool_call(logger, tool_fn.name, kwargs, raw, (time.monotonic() - t0) * 1000)
                    return _FORMATTERS[formatter_key](raw) if formatter_key else raw
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

    enriched_message = (
        f"RELEVANT CONTEXT FROM ERP KNOWLEDGE BASE:\n"
        f"{context}\n\n"
        f"USER REQUEST:\n"
        f"{message}"
    )

    return safe_agent_run(agent, ALL_INVOICE_TOOLS, enriched_message, lc_history)
