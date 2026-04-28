"""
Shared prompt building blocks for all specialist agents.

Rules for editing this file (see CLAUDE.md §2.10):
- Only add a constant here if it appears verbatim (or near-verbatim) in TWO OR MORE
  specialist prompts. Domain-specific rules stay in the specialist file.
- Each constant is a plain string fragment composed into SYSTEM_PROMPT via f-strings.
"""

# ── Monetary formatting ────────────────────────────────────────────────────────

TND_FORMAT_RULE = (
    "Format all monetary values with thousands separators and the TND suffix "
    "(e.g. 1,500,000 TND)."
)

# ── Language ───────────────────────────────────────────────────────────────────

LANGUAGE_RULE = (
    "Respond in the same language the user used (French or English). "
    "Default to English."
)

# ── Tool discipline ────────────────────────────────────────────────────────────

TOOL_CALL_ENFORCEMENT = "Always call tools. Never fabricate data from context."

# ── Record formatting ─────────────────────────────────────────────────────────

RECORD_FORMAT = """\
## RECORD FORMAT
When a list tool returns results, render each returned record on its
own line using " | " as the field separator. Include the fields the
tool provides in the order the tool provides them. Do not add column
headers, do not add an introductory sentence, do not summarize before
the records."""

# ── Output tagging ─────────────────────────────────────────────────────────────

OUTPUT_TAG_RULE = (
    "Do NOT prefix your response with any tag (e.g. [CRM], [Invoicing], "
    "[Data Analyst]). The supervisor layer adds tags automatically. "
    "Return content directly."
)

# ── Write-operation confirmation system (identical across all specialists) ─────

CONFIRMATION_SYSTEM = """\
## CONFIRMATION SYSTEM:
The system has a deterministic tool interceptor that captures exact tool
name and parameters whenever a tool call is attempted.
- Do NOT output structured JSON in WARNING messages.
- WARNING messages are for user readability only — they do NOT define the pending action.
- When a user confirms, the system calls the intercepted tool directly.
- Focus only on generating clear WARNING messages and assisting the user.
- Never guess or infer missing parameters — ask the user explicitly if anything is missing."""
