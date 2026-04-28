"""
CRM Specialist Agent — handles all CRM-related operations.
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

from backend.tools.crm_tools import (
    ALL_CRM_TOOLS,
    list_companies, list_contacts, list_deals, get_pipeline_summary,
    predict_churn, predict_deal_win, get_at_risk_clients,
)
from backend.agents.tool_interceptor import safe_agent_run, _FORMATTERS
from backend.rag.retriever import ERPRetriever
from backend.agents.prompt_parts import (
    TND_FORMAT_RULE, LANGUAGE_RULE, TOOL_CALL_ENFORCEMENT,
    OUTPUT_TAG_RULE, CONFIRMATION_SYSTEM, RECORD_FORMAT,
)

SYSTEM_PROMPT = f"""You are a CRM specialist agent for an IT consulting company.
You ONLY handle CRM operations: companies, contacts, deals, pipeline, and sales totals.

Today's date: {{today}}

## Your tools:
- Query and list companies, contacts, deals, activities
- Calculate won deal pipeline value (get_total_won_deal_value) — this is pipeline outcome, NOT collected revenue
- Create, update, delete companies, contacts, deals, activities

## Rules:
1. READ operations: execute directly and return clear results.
2. WRITE operations: ALWAYS call with confirmed=False first for preview. Wait for explicit user confirmation before calling with confirmed=True.
3. Confirmation keywords: yes, yep, ok, okay, confirm, go ahead, oui, confirme, vas-y, d'accord, sure.
4. {TND_FORMAT_RULE}
5. {LANGUAGE_RULE}
6. Be concise and professional.

## CRITICAL TOOL USAGE RULES:
- When asked to list/show contacts WITHOUT a company filter, call list_contacts() with NO arguments to get all contacts.
- When asked to find/search a contact by name (e.g. "find contact Ahmed"), call list_contacts() and search the results, OR use the name parameter if available.
- NEVER ask the user for a company name just to list contacts — call the tool directly.
- When asked to list deals, call list_deals() directly. Do NOT summarize from context — always call the tool.
- When creating a deal for a person (e.g. "deal for Jihed"), first call list_contacts() to find their company, then use that company name for create_deal().

{RECORD_FORMAT}

{OUTPUT_TAG_RULE}

## HANDLING RESPONSES TO A WARNING MESSAGE:
When the last assistant message was a WARNING (pending operation preview), the user's reply:

1. CONFIRMATION (yes, ok, confirm, oui, vas-y, d'accord, go ahead, sure, yep): Call the tool again with confirmed=True and the EXACT SAME parameters shown in the WARNING. Do not ask again.

2. PARAMETER UPDATE: Extract original parameters from WARNING, merge new info, call with confirmed=False for updated preview.

{CONFIRMATION_SYSTEM}

{TOOL_CALL_ENFORCEMENT}"""


_WRITE_KEYWORDS = [
    "create", "add", "new", "make",
    "update", "edit", "modify", "change",
    "delete", "remove", "archive",
    # French
    "créer", "crée", "ajouter", "nouveau", "nouvelle",
    "modifier", "supprimer", "archiver",
]

# Compiled once — word boundaries prevent "add" matching "address", "new" matching "renew"
_WRITE_OP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in sorted(_WRITE_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Detects a dynamic entity filter in a list query — signals that the LLM must
# extract filter params rather than using a hardcoded _LIST_TOOL_MAP entry.
# Known gap: French "de X" company filters (e.g. "contacts de BNA") — too broad
# to match safely; those queries fall through to unfiltered deterministic call.
_LIST_ENTITY_FILTER_RE = re.compile(
    r'\b(?:for|from|at|pour|chez)\s+\w'
    r'|\bnamed?\s+\w'
    r'|\bcalled\s+\w'
    r'|\bin\s+(?:the\s+)?\w+\s+(?:industry|sector)',
    re.IGNORECASE,
)

# Supervisor directive injected when the user confirms a WARNING preview
_SUPERVISOR_CONFIRMATION_PREFIX = "The user has confirmed the previous action."

_LIST_INTENTS = [
    # Contacts
    "list contacts", "show contacts", "all contacts", "get contacts",
    "list all contacts", "show all contacts",
    "every contact",
    "liste des contacts", "afficher contacts", "afficher les contacts",
    "montrer les contacts", "tous les contacts",
    "chaque contact",
    # Companies
    "list companies", "show companies", "all companies", "get companies",
    "list all companies", "show all companies",
    "every company", "complete list", "complete list of",
    "list clients", "show clients", "all clients",
    "every client",
    "client companies",
    "list prospects", "show prospects", "all prospects",
    "every prospect",
    "prospect companies",
    "list inactive", "inactive companies",
    "liste des entreprises", "afficher les entreprises", "toutes les entreprises",
    "montrer les entreprises",
    "chaque entreprise", "chaque client",
    # Deals
    "list deals", "show deals", "all deals", "get deals",
    "list all deals", "show all deals",
    "every deal",
    "list won deals", "won deals", "list open deals", "open deals",
    "list lost deals", "lost deals", "list on_hold deals", "on hold deals",
    "liste des deals", "afficher les deals", "tous les deals",
    # Pipeline
    "pipeline", "pipeline summary", "show pipeline",
    # At-risk / churn signal queries
    "at risk clients", "at-risk clients", "churn signals",
    "clients at risk", "clients with churn", "which clients have churn",
]


# Ordered most-specific first. Reached when _LIST_ENTITY_FILTER_RE finds no
# dynamic filter in the message. Entity-lookup intents ("find company X",
# "get contact Y") are absent — they fall through to safe_agent_run.
_LIST_TOOL_MAP = [
    # Deals — status-filtered before generic
    ("won deals",              list_deals,            {"status": "won"},      "list_deals"),
    ("lost deals",             list_deals,            {"status": "lost"},     "list_deals"),
    ("open deals",             list_deals,            {"status": "open"},     "list_deals"),
    ("on hold deals",          list_deals,            {"status": "on_hold"},  "list_deals"),
    ("on_hold deals",          list_deals,            {"status": "on_hold"},  "list_deals"),
    ("tous les deals",         list_deals,            {},                     "list_deals"),
    ("deals",                  list_deals,            {},                     "list_deals"),
    # Contacts
    ("tous les contacts",      list_contacts,         {},                     "list_contacts"),
    ("contacts",               list_contacts,         {},                     "list_contacts"),
    # Companies — filtered before generic
    ("inactive companies",     list_companies,        {"status": "inactive"}, "list_companies"),
    ("list inactive",          list_companies,        {"status": "inactive"}, "list_companies"),
    ("inactive",               list_companies,        {"status": "inactive"}, "list_companies"),
    ("list clients",           list_companies,        {"status": "client"},   "list_companies"),
    ("all clients",            list_companies,        {"status": "client"},   "list_companies"),
    ("show clients",           list_companies,        {"status": "client"},   "list_companies"),
    ("client companies",       list_companies,        {"status": "client"},   "list_companies"),
    ("list prospects",         list_companies,        {"status": "prospect"}, "list_companies"),
    ("all prospects",          list_companies,        {"status": "prospect"}, "list_companies"),
    ("show prospects",         list_companies,        {"status": "prospect"}, "list_companies"),
    ("prospect companies",     list_companies,        {"status": "prospect"}, "list_companies"),
    ("toutes les entreprises", list_companies,        {},                     "list_companies"),
    ("entreprises",            list_companies,        {},                     "list_companies"),
    ("companies",              list_companies,        {},                     "list_companies"),
    ("every company",          list_companies,        {},                     "list_companies"),
    ("every client",           list_companies,        {"status": "client"},   "list_companies"),
    ("every prospect",         list_companies,        {"status": "prospect"}, "list_companies"),
    ("every contact",          list_contacts,         {},                     "list_contacts"),
    ("every deal",             list_deals,            {},                     "list_deals"),
    ("complete list",          list_companies,        {},                     "list_companies"),
    # Pipeline — structured prose, no formatter
    ("pipeline",               get_pipeline_summary,  {},                     None),
    # At-risk clients — ordered most-specific first
    ("which clients have churn", get_at_risk_clients, {},                     None),
    ("clients with churn",       get_at_risk_clients, {},                     None),
    ("clients at risk",          get_at_risk_clients, {},                     None),
    ("churn signals",            get_at_risk_clients, {},                     None),
    ("at-risk clients",          get_at_risk_clients, {},                     None),
    ("at risk clients",          get_at_risk_clients, {},                     None),
]


_DEAL_PREDICT_INTENTS = [
    "predict deal", "deal prediction", "win probability",
    "deal chances", "chance of winning", "will we win",
    "deal outcome for", "predict deal win",
]

# Captures a deal ID (integer) from the message, e.g. "deal 42", "deal #42", "deal id 42"
_DEAL_ID_RE = re.compile(r'\bdeal\s+(?:id\s+|#\s*)?(\d+)\b', re.IGNORECASE)


_CHURN_INTENTS = [
    "churn risk", "predict churn", "churn for", "churn of",
    "at risk of churning", "risk of churn", "client health for",
    "risque de churn", "risque d'attrition",
]

# Captures company name after "churn risk for X", "predict churn for X", etc.
_CHURN_FOR_RE = re.compile(
    r'(?:churn\s+(?:risk\s+)?(?:for|of)|predict\s+churn\s+(?:for|of)|client\s+health\s+for)'
    r'\s+(.+?)[\?\.\!]*\s*$',
    re.IGNORECASE,
)


def _is_confirmation(message: str) -> bool:
    from backend.agents.supervisor import _is_positive_confirmation
    return _is_positive_confirmation(message)


def _is_write_operation(message: str) -> bool:
    return bool(_WRITE_OP_RE.search(message))


def _last_warning_in_history(history: Optional[List[Dict]]) -> Optional[str]:
    """
    Return WARNING content only if the most recent assistant turn is a WARNING.
    Stops at the first assistant message — never resurrects warnings from older turns.
    """
    for msg in reversed(history or []):
        if msg.get("role") == "assistant":
            content = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            if re.match(r"^warning[!:\s]", content, re.IGNORECASE):
                return content
            return None  # Most recent assistant turn is not a WARNING — stop
    return None


def extract_company_from_message(
    message: str, history: Optional[List[Dict]]
) -> Optional[str]:
    """
    Return the most specific matching company name found in the message, or None.
    Sorts by name length descending so 'Acme Corporation' beats 'Acme'.
    Uses word boundaries to avoid false substring matches (e.g. 'Tech' in 'Technology').
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


# ── Agent caching (daily refresh to keep system-prompt date current) ─────────

_crm_agent_instance: Optional[AgentExecutor] = None
_crm_agent_date: Optional[str] = None


def _get_crm_agent() -> AgentExecutor:
    global _crm_agent_instance, _crm_agent_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _crm_agent_instance is None or _crm_agent_date != today:
        _crm_agent_instance = create_crm_agent()
        _crm_agent_date = today
    return _crm_agent_instance


def create_crm_agent() -> AgentExecutor:
    llm = get_llm()
    today = datetime.now().strftime("%A, %B %d, %Y")
    system_with_date = SYSTEM_PROMPT.format(today=today)
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_with_date),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm=llm, tools=ALL_CRM_TOOLS, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=ALL_CRM_TOOLS,
        verbose=True,
        max_iterations=3,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


def run_crm_agent(message: str, history: List[Dict] = None) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")

    # Build LangChain history — strip [TAG]\n prefix from assistant messages (W7)
    lc_history = []
    for msg in (history or []):
        if msg.get("role") == "human":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            clean = re.sub(r"^\[[^\]]+\]\s*", "", msg.get("content", "").strip())
            lc_history.append(AIMessage(content=clean))

    agent = _get_crm_agent()

    # Path 0: Supervisor confirmation directive — bypass RAG and LIST check
    if message.startswith(_SUPERVISOR_CONFIRMATION_PREFIX):
        return safe_agent_run(agent, ALL_CRM_TOOLS, message, lc_history)

    # Path 2: Write operation — checked BEFORE list intents so that messages
    # containing both a write keyword and a list phrase (e.g. "find contact and
    # create a deal") are handled by the write path with date injection.
    warning = _last_warning_in_history(history)
    if warning and _is_confirmation(message):
        enriched_message = (
            f"TODAY'S DATE: {today}\n\n"
            f"CONFIRMED OPERATION — call the tool with confirmed=True.\n\n"
            f"{warning}\n\n"
            f"USER CONFIRMATION: \"{message}\"\n\n"
            f"Call the tool NOW with confirmed=True."
        )
        return safe_agent_run(agent, ALL_CRM_TOOLS, enriched_message, lc_history)

    if _is_write_operation(message):
        enriched_message = f"TODAY'S DATE: {today}\n\nUSER REQUEST:\n{message}"
        return safe_agent_run(agent, ALL_CRM_TOOLS, enriched_message, lc_history)

    # Path D: Deal win prediction — deterministic bypass; 7B model is unreliable here.
    if any(intent in message.lower() for intent in _DEAL_PREDICT_INTENTS):
        m = _DEAL_ID_RE.search(message)
        if m:
            deal_id = int(m.group(1))
            t0 = time.monotonic()
            result = predict_deal_win.invoke({"deal_id": deal_id})
            log_tool_call(logger, "predict_deal_win", {"deal_id": deal_id}, result, (time.monotonic() - t0) * 1000)
            return result
        # No deal ID found — fall through to agent

    # Path C: Churn prediction — deterministic bypass; 7B model is unreliable here.
    if any(intent in message.lower() for intent in _CHURN_INTENTS):
        company_name = None
        m = _CHURN_FOR_RE.search(message)
        if m:
            company_name = m.group(1).strip().rstrip("?!.,")
        if not company_name:
            company_name = extract_company_from_message(message, history)
        if company_name:
            invoke_args = {"company_name": company_name}
            t0 = time.monotonic()
            result = predict_churn.invoke(invoke_args)
            log_tool_call(logger, "predict_churn", invoke_args, result, (time.monotonic() - t0) * 1000)
            return result
        # Company name not resolved — fall through to agent

    # Path 1: List intent — deterministic unless a dynamic entity filter is present.
    # With a filter: LLM extracts params; is_list_query=True makes safe_agent_run
    # replace the LLM prose with the raw formatter output from intermediate steps.
    msg_lower = message.lower().strip()
    if any(intent in msg_lower for intent in _LIST_INTENTS):
        has_entity_filter = bool(_LIST_ENTITY_FILTER_RE.search(msg_lower))
        if not has_entity_filter:
            for keyword, tool_fn, kwargs, formatter_key in _LIST_TOOL_MAP:
                if keyword in msg_lower:
                    t0 = time.monotonic()
                    raw = str(tool_fn.invoke(kwargs))
                    log_tool_call(logger, tool_fn.name, kwargs, raw, (time.monotonic() - t0) * 1000)
                    return _FORMATTERS[formatter_key](raw) if formatter_key else raw
        # Entity filter present or no _LIST_TOOL_MAP match — LLM path with formatter guard.
        return safe_agent_run(agent, ALL_CRM_TOOLS, message, lc_history, is_list_query=True)

    # Path 3: Read operation with RAG context
    retriever = ERPRetriever(module="crm", top_k=5)
    docs = retriever.retrieve(message)
    context = retriever.format_context(docs)

    company_name = extract_company_from_message(message, history)
    if company_name:
        company_docs = retriever.retrieve_for_company(company_name, message)
        company_context = retriever.format_context(company_docs)
        context = company_context + "\n\n" + context

    enriched_message = (
        f"TODAY'S DATE: {today}\n\n"
        f"BACKGROUND CONTEXT (read-only — do NOT use company/contact names here as "
        f"filter arguments unless the user explicitly named them in their request):\n"
        f"{context}\n\n"
        f"USER REQUEST:\n"
        f"{message}"
    )
    return safe_agent_run(agent, ALL_CRM_TOOLS, enriched_message, lc_history)