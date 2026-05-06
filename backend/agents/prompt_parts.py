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
List tools return a pre-formatted markdown table beginning with 'Showing X of Y results:'. \
Relay the complete tool output verbatim — every row, the header line, unchanged. \
Do not reformat, summarize, or omit rows. The table is already fully formatted in Python.

When a tool returns a pre-formatted markdown table, relay it to the user EXACTLY as returned — \
do not reformat, summarize, or select rows. Copy the tool output verbatim including the \
'Showing X of Y' header line.

For a single-record result, use a vertical key: value list (one field per line), not a table."""

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
- When a tool returns a WARNING preview, relay it to the user verbatim without rewording.
- Never guess or infer missing parameters — ask the user explicitly if anything is missing."""
