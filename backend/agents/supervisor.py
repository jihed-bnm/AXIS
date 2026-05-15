"""
Supervisor Agent — routes user messages to the correct specialist agent.
"""

import re
from typing import List, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate
from backend.agents.llm import get_llm

from backend.agents.crm_specialist import run_crm_agent
from backend.agents.invoice_specialist import run_invoice_agent
from backend.agents.chart_agent import run_chart_agent
from backend.error_handler import validate_user_input, handle_agent_error, logger

from dotenv import load_dotenv
load_dotenv()


# ── Fast Keyword Router ───────────────────────────────────────────────────────

KEYWORD_RULES: Dict[str, List[str]] = {
    "INVOICING": [
        "invoice", "invoices", "payment", "payments", "revenue", "billing",
        "unpaid", "overdue", "receipt", "receipts", "tax", "tva", "facture",
        "facturation", "paiement",
    ],
    "CRM": [
        "deal", "deals", "contact", "contacts", "company", "companies",
        "pipeline", "prospect", "prospects", "lead", "leads",
        "opportunity", "opportunities", "activit",
        "client", "clients", "delete", "remove", "create contact",
        "add contact", "new contact", "create company", "add company",
        "new company", "create deal", "add deal", "new deal",
        "update contact", "update company", "update deal",
        "churn", "churn risk", "at risk", "at-risk",
        "retention", "predict churn", "client health",
        "deal prediction", "win probability", "deal chances",
        "predict deal", "deal outcome",
    ],
}

VALID_MODULES = {"CRM", "INVOICING", "GENERAL", "CHART"}

# Matches "top 5", "top 10", "above 50%", "below 30%", "above 0.5%", etc.
# These patterns unambiguously signal a chart/filter request and must be caught
# before CRM keywords like "clients" or "deals" can match.
_CHART_FILTER_RE = re.compile(
    r'\btop\s+\d+\b'
    r'|'
    r'\b(?:above|below)\s+\d+(?:\.\d+)?%',
    re.IGNORECASE,
)

_CHART_KEYWORDS = [
    "bar chart", "line chart", "pie chart", "donut chart",
    "scatter chart", "funnel chart", "area chart",
    "create a chart", "generate a chart", "show me a chart",
    "create chart", "generate chart", "visualize", "visualisation", "visualization",
    "my charts", "saved charts", "list charts", "delete chart",
    "chart of", "graph of", "plot of",
]


def fast_route(message: str) -> Optional[str]:
    msg = message.lower()

    # Tier 1a: regex pre-check — "top N" or "above/below X%" are chart-filter signals
    # that must beat CRM keywords ("clients", "deals", "win probability", etc.)
    if _CHART_FILTER_RE.search(message):
        return "CHART"

    # Tier 1b: chart keyword check — also runs before CRM so "churn chart" beats "churn"
    if any(k in msg for k in _CHART_KEYWORDS):
        return "CHART"

    # INVOICING before CRM — "invoice for client X" must go to invoicing
    for module in ["INVOICING", "CRM"]:
        if any(k in msg for k in KEYWORD_RULES[module]):
            return module
    return None


# ── LLM Router ────────────────────────────────────────────────────────────────

ROUTER_PROMPT = """You are a routing layer for the AXIS operational management platform. Your ONLY job is to
classify the user's message into exactly one of these categories:

CRM        — companies, contacts, deals, pipeline, leads, activities
INVOICING  — invoices, payments, revenue totals, billing
CHART      — charts, graphs, data visualizations, plots
GENERAL    — greetings, help requests, questions about what the system can do

CRITICAL RULES:
- CREATE / UPDATE / DELETE intent always goes to the specialist, NEVER to GENERAL.
- Route to the specialist whose domain best matches the user's request.

Examples:
  "list our clients"              → CRM
  "add a new company"             → CRM
  "what is the churn risk for X?" → CRM
  "which clients are at risk?"    → CRM
  "what are the chances of winning deal 42?" → CRM
  "show overdue invoices"         → INVOICING
  "create invoice for Acme"       → INVOICING
  "show a bar chart of deals"     → CHART
  "what can you do"               → GENERAL
  "hello"                         → GENERAL

Respond with ONLY ONE of these exact words (no punctuation, no explanation):
CRM, INVOICING, CHART, GENERAL

User message: {message}

Agent:"""


# ── Confirmation Flow ─────────────────────────────────────────────────────────

_TAG_TO_MODULE: Dict[str, str] = {
    "crm":          "CRM",
    "invoicing":    "INVOICING",
    "data analyst": "CHART",
}

_POSITIVE_CONFIRMATION_KEYWORDS = {
    "yes", "yep", "yeah", "yup", "confirm", "confirmed",
    "oui", "ok", "okay",
    "vas-y", "d'accord", "sure",
}

_NEGATIVE_CONFIRMATION_KEYWORDS = {
    "no", "non", "nope", "nah", "cancel", "annuler", "abort",
}

# Combined set used for "is this a confirmation turn at all?" check
_CONFIRMATION_KEYWORDS = _POSITIVE_CONFIRMATION_KEYWORDS | _NEGATIVE_CONFIRMATION_KEYWORDS

# Multi-word / punctuated phrases (substring match is safe — they're distinctive)
_CONFIRMATION_PHRASES = frozenset(
    kw for kw in _CONFIRMATION_KEYWORDS if " " in kw or "-" in kw or "'" in kw
)
_POSITIVE_PHRASES = frozenset(
    kw for kw in _POSITIVE_CONFIRMATION_KEYWORDS if " " in kw or "-" in kw or "'" in kw
)
_NEGATIVE_PHRASES = frozenset(
    kw for kw in _NEGATIVE_CONFIRMATION_KEYWORDS if " " in kw or "-" in kw or "'" in kw
)

# Single-word tokens — word-boundary regex to prevent "no" matching "notion",
# "ok" matching "look", "yes" matching "yesterday", etc.
_CONFIRMATION_WORDS = _CONFIRMATION_KEYWORDS - _CONFIRMATION_PHRASES
_POSITIVE_WORDS = _POSITIVE_CONFIRMATION_KEYWORDS - _POSITIVE_PHRASES
_NEGATIVE_WORDS = _NEGATIVE_CONFIRMATION_KEYWORDS - _NEGATIVE_PHRASES

_CONFIRMATION_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(_CONFIRMATION_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_POSITIVE_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(_POSITIVE_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_NEGATIVE_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(_NEGATIVE_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _is_confirmation_keyword(message: str) -> bool:
    """Return True if the message contains any confirmation keyword (positive or negative)."""
    msg = message.strip().lower()
    if any(phrase in msg for phrase in _CONFIRMATION_PHRASES):
        return True
    return bool(_CONFIRMATION_WORD_RE.search(msg))


def _is_positive_confirmation(message: str) -> bool:
    """Return True only for affirmative confirmation keywords (yes, ok, go ahead…)."""
    msg = message.strip().lower()
    if any(phrase in msg for phrase in _POSITIVE_PHRASES):
        return True
    return bool(_POSITIVE_WORD_RE.search(msg))


def _is_negative_confirmation(message: str) -> bool:
    """Return True only for negative/cancellation keywords (no, cancel, nope…)."""
    msg = message.strip().lower()
    if any(phrase in msg for phrase in _NEGATIVE_PHRASES):
        return True
    return bool(_NEGATIVE_WORD_RE.search(msg))


# Patterns that mean a *tool* was previewed with confirmed=False.
# When one of these is present in the last assistant message, confirming
# means "call the same tool again with confirmed=True".
_WRITE_PREVIEW_PATTERNS: tuple = (
    "WARNING:", "about to CREATE", "about to UPDATE", "about to DELETE",
)

# Disambiguation phrases: when the last CRM response contains one of these,
# a follow-up short reply (e.g. "BNA") is sticky-routed back to CRM rather
# than falling through to the LLM router (which classifies 3-letter strings as GENERAL).
# Both conditions must be true — [CRM] tag AND phrase — so false-positive risk is low.
_DISAMBIGUATION_PATTERNS: tuple = (
    "did you mean",
    "could you confirm",
    "could you please confirm",
    "which one",
    "there might be a typo",
    "would you like to",
    "would you like me to",
    "do you want to",
    "do you want me to",
    "shall i create",
    "please clarify",
    "voulez-vous creer",
    "voulez-vous que je",
    "not found",
    "introuvable",
    "might be a typo",
    "is that correct",
    "do you mean",
    "vouliez-vous dire",
    "est-ce que vous voulez dire",
)

# Broader set: any pattern that means the conversation is mid-flow and a
# short "yes/ok" reply should stay in the same specialist module rather than
# being re-routed through the LLM router (which would classify it as GENERAL).
_CONTEXT_CONTINUATION_PATTERNS: tuple = _WRITE_PREVIEW_PATTERNS + (
    "Please confirm", "Confirm the", "please provide", "Please provide",
    "need me to find", "could you provide", "Could you please provide",
    "Would you like", "Shall I", "Do you want", "Should I",
    "Which company", "which company", "What company", "what company",
    "répondez par", "confirming",
)


def _last_module_from_history(history: List[Dict]) -> Optional[str]:
    """
    Extract the last active specialist module by reading the [TAG] prefix
    that the supervisor attaches to every assistant response before saving it.

    This is the zero-migration alternative to storing last_module in the DB:
    the information is already in the history, so no schema change is needed.
    Returns None for GENERAL (no specialist active) or when history is empty.
    """
    for entry in reversed(history):
        if entry.get("role") == "assistant":
            m = re.match(r"^\[([^\]]+)\]", entry.get("content", "").strip())
            if m:
                return _TAG_TO_MODULE.get(m.group(1).lower())  # None for unknown tags
    return None


def check_if_confirmation(message: str, chat_history: List[Dict]) -> Optional[str]:
    """
    Returns the module name if there is a pending WARNING/context-continuation
    operation in context.  Only inspects the single most-recent assistant
    message to prevent stale matches from earlier in the conversation.
    """
    if not _is_confirmation_keyword(message):
        return None

    # Guard: "cancel invoice INV-001" / "annuler facture X" — "cancel" and "annuler"
    # are also domain verbs. If the message fast-routes to a specialist, it is a fresh
    # domain command, not a meta-operation cancellation, even though it contains a
    # negative-confirmation keyword.
    if _is_negative_confirmation(message) and fast_route(message) is not None:
        return None

    last_assistant = None
    for entry in reversed(chat_history):
        if entry.get("role") == "assistant":
            last_assistant = entry.get("content", "")
            break

    if not last_assistant or not any(p in last_assistant for p in _CONTEXT_CONTINUATION_PATTERNS):
        return None

    # Primary: read the [TAG] from the last assistant message
    match = re.match(r'^\[([^\]]+)\]', last_assistant.strip())
    if match:
        tag = match.group(1).lower()
        module = _TAG_TO_MODULE.get(tag)
        if module:
            logger.info(f"[Supervisor] Confirmation detected — re-routing to: {module}")
            return module

    # Secondary: domain-keyword inference from the last message only (W5 fix)
    if any(w in last_assistant for w in ["contact", "company", "deal", "activit", "client"]):
        logger.info("[Supervisor] Confirmation inferred (keyword) → CRM")
        return "CRM"
    if any(w in last_assistant for w in ["invoice", "payment", "facture"]):
        logger.info("[Supervisor] Confirmation inferred (keyword) → INVOICING")
        return "INVOICING"

    # Fallback: use _last_module_from_history which reads tags across history
    module = _last_module_from_history(chat_history)
    if module:
        logger.info(f"[Supervisor] Confirmation fallback (history tag) → {module}")
        return module

    logger.info("[Supervisor] Confirmation: no module detected — falling through to normal routing")
    return None


# ── General Handler ───────────────────────────────────────────────────────────

GENERAL_RESPONSE_PROMPT = """You are a helpful assistant for the AXIS operational management platform, serving an IT consulting company.
You manage 2 specialist agents: Sales Intelligence and Finance.
Answer the user's general question or greeting naturally and briefly.
If they ask what you can do, explain the 2 modules with short example queries for each.

CRM: manage companies, contacts, deals, pipeline, activities.
Invoicing: manage invoices, payments, revenue reports.

IMPORTANT: Always respond in English unless the user wrote in French.

User message: {message}"""


def handle_general(message: str) -> str:
    try:
        llm = get_llm()
        prompt = ChatPromptTemplate.from_template(GENERAL_RESPONSE_PROMPT)
        chain = prompt | llm
        result = chain.invoke({"message": message})
        return result.content.strip()
    except Exception as e:
        logger.error(f"[Supervisor] General handler failed: {e}", exc_info=True)
        return "Hello! I'm the AXIS assistant. How can I help you today?"


def _strip_agent_tag(response: str) -> str:
    """Remove ALL [TAG] prefixes agents add to their responses."""
    cleaned = response.strip()
    # Keep stripping leading [TAG] patterns until none remain
    while True:
        match = re.match(r'^\s*\[[^\]]+\]\s*', cleaned)
        if match:
            cleaned = cleaned[match.end():].strip()
        else:
            break
    return cleaned


# ── Routing Orchestrator ──────────────────────────────────────────────────────

def route_message(message: str) -> str:
    fast = fast_route(message)
    if fast:
        logger.info(f"[Supervisor] Fast-routed to: {fast}")
        return fast

    try:
        llm = get_llm()
        prompt = ChatPromptTemplate.from_template(ROUTER_PROMPT)
        chain = prompt | llm
        result = chain.invoke({"message": message})
        module = result.content.strip().upper().strip(".,!?\"'")

        if module in VALID_MODULES:
            logger.info(f"[Supervisor] LLM-routed to: {module}")
            return module

        logger.warning(f"[Supervisor] LLM returned unrecognized module '{module}', defaulting to GENERAL")
        return "GENERAL"

    except Exception as e:
        logger.error(f"[Supervisor] LLM routing failed: {e}", exc_info=True)
        return "GENERAL"


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_agent(user_message: str, chat_history: List[Dict] = None) -> str:
    input_error = validate_user_input(user_message)
    if input_error:
        return input_error.user_message

    history = chat_history or []

    # Tier 0: confirmation short-circuit — must check BEFORE routing
    confirmed_module = check_if_confirmation(user_message, history)

    # Compute once — used by both the confirmed path and Tier 0.5
    last_assistant = next(
        (e["content"] for e in reversed(history) if e.get("role") == "assistant"), ""
    )

    if confirmed_module:
        module = confirmed_module

        # W2: if the user replied negatively, cancel the pending operation
        if _is_negative_confirmation(user_message):
            logger.info(f"[Supervisor] Negative confirmation — cancelling pending operation in {module}")
            return f"[{module}]\nOperation cancelled."

        if any(p in last_assistant for p in _WRITE_PREVIEW_PATTERNS):
            # Tool-preview confirmation: replace with unambiguous execution
            # directive so the specialist doesn't have to interpret "yes".
            if _is_positive_confirmation(user_message):
                user_message = (
                    "The user has confirmed the previous action. "
                    "Re-execute it now using confirmed=True with the exact same parameters shown in the WARNING."
                )
                logger.info(f"[Supervisor] Write-preview confirmation → {module}")
            else:
                # Ambiguous — pass original message; agent will handle
                logger.info(f"[Supervisor] Write-preview (ambiguous) → {module}, preserving message")
        else:
            # Question-type continuation: pass original reply with full history
            logger.info(f"[Supervisor] Question-type confirmation → {module}, preserving user message")
    else:
        # Tier 0.5: context continuation — if the last assistant message
        # signals mid-flow state, keep routing to the same specialist module
        # instead of letting the LLM router classify a short reply as GENERAL.
        if last_assistant and any(p in last_assistant for p in _WRITE_PREVIEW_PATTERNS):
            # Only activate Tier 0.5 for actual WARNING previews, not for every
            # clarifying question — prevents fresh requests being mis-routed.
            # Primary: read the [TAG] from the last assistant message —
            # zero-cost, already in history, no extra storage needed.
            module = _last_module_from_history(history)
            if module:
                logger.info(f"[Supervisor] Context continuation (tag) → {module}")
            else:
                # Secondary: domain-keyword inference from the message text
                if any(w in last_assistant for w in ["contact", "company", "deal", "activit", "client"]):
                    module = "CRM"
                    logger.info("[Supervisor] Context continuation (keyword) → CRM")
                elif any(w in last_assistant for w in ["invoice", "payment", "facture"]):
                    module = "INVOICING"
                    logger.info("[Supervisor] Context continuation (keyword) → INVOICING")
                else:
                    module = route_message(user_message)
        else:
            # Tier 0.5b: disambiguation-sticky — when the previous CRM response
            # contained a disambiguation prompt, route the follow-up to CRM
            # (e.g. bare "BNA" after "did you mean BNA?").
            # Fast-route always wins if the new message contains explicit domain
            # keywords (e.g. "give me a list of invoices" must go to INVOICING).
            if (last_assistant.strip().startswith("[CRM]")
                    and any(p in last_assistant.lower() for p in _DISAMBIGUATION_PATTERNS)):
                fast = fast_route(user_message)
                module = fast if fast else "CRM"
                logger.info(f"[Supervisor] Disambiguation-sticky -> {module}")
            else:
                module = route_message(user_message)

    try:
        if module == "CRM":
            response = run_crm_agent(user_message, history)
            tag = "CRM"

        elif module == "INVOICING":
            response = run_invoice_agent(user_message, history)
            tag = "Invoicing"

        elif module == "CHART":
            response = run_chart_agent(user_message, history)
            tag = "Data Analyst"

        else:
            response = handle_general(user_message)
            tag = "AXIS"

        # Strip any [TAG] the agent added itself to prevent double-tagging
        clean_response = _strip_agent_tag(response)
        return f"[{tag}]\n{clean_response}"

    except Exception as e:
        logger.error(f"[{module}] Agent execution failed", exc_info=True)
        error_response = handle_agent_error(e, module)
        return f"[Error]\n{error_response}"