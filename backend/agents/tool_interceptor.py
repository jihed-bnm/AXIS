"""
Tool Interceptor — fallback handler for agents that return raw tool-call JSON
instead of executing the tool (common with weaker local LLMs).

Usage:
    result = safe_agent_run(agent, tools, message, lc_history)
"""

import json
import re
import time
from typing import List, Any, Dict

from langchain.agents import AgentExecutor
from langchain_core.tools import BaseTool
from backend.error_handler import logger
from logging_config import log_tool_call


# ── List-query deterministic formatters ──────────────────────────────────────

def _fmt_contacts(raw: str) -> str:
    header_lines = []
    data_lines = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s+(.*)', line)
        if not m:
            if line:
                header_lines.append(line)
            continue
        id_, rest = m.group(1), m.group(2)
        fields = [f.strip() for f in rest.split(' | ')]
        if len(fields) >= 4:
            role = fields[1] if fields[1] and fields[1].lower() not in ('none', '') else '-'
            data_lines.append(f"{id_} | {fields[0]} | {role} | {fields[2]} | {fields[3]}")
        else:
            data_lines.append(f"{id_} | {rest}")
    all_lines = header_lines + data_lines
    return '\n'.join(all_lines) if all_lines else 'No records found.'


def _fmt_deals(raw: str) -> str:
    header_lines = []
    data_lines = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s+(.*)', line)
        if not m:
            if line:
                header_lines.append(line)
            continue
        id_, rest = m.group(1), m.group(2)
        fields = [f.strip() for f in rest.split(' | ')]
        if len(fields) >= 5:
            stage = re.sub(r'^Stage:\s*', '', fields[4], flags=re.IGNORECASE)
            data_lines.append(f"{id_} | {fields[0]} | {fields[1]} | {fields[2]} | {fields[3]} | {stage}")
        else:
            data_lines.append(f"{id_} | {rest}")
    all_lines = header_lines + data_lines
    return '\n'.join(all_lines) if all_lines else 'No records found.'


def _fmt_invoices(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s+(.*)', line)
        if not m:
            continue
        id_, rest = m.group(1), m.group(2)
        fields = [f.strip() for f in rest.split(' | ')]
        # tool order: number | company | status | amount | Due: date
        # target:     id | number | company | amount | status | date
        if len(fields) >= 5:
            due = re.sub(r'^Due:\s*', '', fields[4], flags=re.IGNORECASE)
            lines.append(f"{id_} | {fields[0]} | {fields[1]} | {fields[3]} | {fields[2]} | {due}")
        else:
            lines.append(f"{id_} | {rest}")
    return '\n'.join(lines) if lines else 'No records found.'


def _fmt_companies(raw: str) -> str:
    header_lines = []
    data_lines = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s+(.*)', line)
        if not m:
            if line:
                header_lines.append(line)
            continue
        id_, rest = m.group(1), m.group(2)
        fields = [f.strip() for f in rest.split(' | ')]
        # tool order: name | industry | city | Status: status
        if len(fields) >= 4:
            status = re.sub(r'^Status:\s*', '', fields[3], flags=re.IGNORECASE)
            data_lines.append(f"{id_} | {fields[0]} | {fields[1]} | {fields[2]} | {status}")
        else:
            data_lines.append(f"{id_} | {rest}")
    all_lines = header_lines + data_lines
    return '\n'.join(all_lines) if all_lines else 'No records found.'


def _fmt_invoice(raw: str) -> str:
    """Pass-through formatter — get_invoice output is already well-structured."""
    return raw.strip() if raw.strip() else 'Invoice not found.'


def _fmt_revenue_summary(raw: str) -> str:
    """Pass-through formatter — get_revenue_summary output is already well-structured."""
    return raw.strip() if raw.strip() else 'No revenue data found.'


def _fmt_charts(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^\[ID:\s*(\d+)\]\s+(.*)', line)
        if not m:
            continue
        id_, rest = m.group(1), m.group(2)
        fields = [f.strip() for f in rest.split(' | ')]
        # tool order: title | Type: type | Created: datetime
        if len(fields) >= 3:
            type_ = re.sub(r'^Type:\s*', '', fields[1], flags=re.IGNORECASE)
            created = re.sub(r'^Created:\s*', '', fields[2], flags=re.IGNORECASE)
            lines.append(f"{id_} | {fields[0]} | {type_} | {created}")
        else:
            lines.append(f"{id_} | {rest}")
    return '\n'.join(lines) if lines else 'No records found.'


_FORMATTERS = {
    'list_contacts':      _fmt_contacts,
    'list_deals':         _fmt_deals,
    'list_invoices':      _fmt_invoices,
    'list_companies':     _fmt_companies,
    'get_invoice':        _fmt_invoice,
    'get_revenue_summary': _fmt_revenue_summary,
    'list_saved_charts':  _fmt_charts,
}

# ── JSON normalisation ────────────────────────────────────────────────────────

def _normalize_python_literals(text: str) -> str:
    """
    Replace Python-style literals that break json.loads:
      False → false,  True → true,  None → null
    Uses word-boundary regex so it doesn't corrupt string values.
    """
    text = re.sub(r'\bFalse\b', 'false', text)
    text = re.sub(r'\bTrue\b',  'true',  text)
    text = re.sub(r'\bNone\b',  'null',  text)
    return text


# ── JSON extraction strategies ────────────────────────────────────────────────

def _try_parse(text: str) -> dict | None:
    """Attempt json.loads after normalising Python literals. Returns dict or None."""
    try:
        obj = json.loads(_normalize_python_literals(text))
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_outermost_object(text: str) -> str | None:
    """
    Walk the string character by character to extract the first complete
    JSON object (balanced braces). More reliable than a greedy regex for
    nested structures.
    """
    depth = 0
    start = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i + 1]

    return None


def _extract_tool_call(text: str) -> dict | None:
    """
    Try every extraction strategy in order. Returns a dict with at least
    'name' and one of 'parameters'/'arguments', or None if nothing matches.
    """
    # 1. Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = cleaned.replace('```', '').strip()

    # 2. Try the entire cleaned string as JSON
    obj = _try_parse(cleaned)
    if obj and "name" in obj and ("parameters" in obj or "arguments" in obj):
        return obj

    # 3. Extract the first balanced JSON object from anywhere in the text
    fragment = _extract_outermost_object(cleaned)
    if fragment:
        obj = _try_parse(fragment)
        if obj and "name" in obj and ("parameters" in obj or "arguments" in obj):
            return obj

    # 4. Fallback: greedy regex (handles simple non-nested cases)
    match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
    if match:
        obj = _try_parse(match.group())
        if obj and "name" in obj and ("parameters" in obj or "arguments" in obj):
            return obj

    return None


# ── Tool lookup ───────────────────────────────────────────────────────────────

def _find_tool(name: str, tools: List[BaseTool]) -> BaseTool | None:
    """Return the tool whose name matches, case-insensitively."""
    for tool in tools:
        if tool.name.lower() == name.lower():
            return tool
    return None


# ── Pending-action capture ────────────────────────────────────────────────────

_WARNING_PATTERNS = ("WARNING:", "about to CREATE", "about to UPDATE", "about to DELETE")
_HALLUCINATED_CONFIRM_RE = re.compile(
    r'^\s*(?:warning[!:]|i\s+am\s+about\s+to)\b'
    r'|do\s+you\s+want\s+to\s+proceed'
    r'|please\s+confirm\s+with',
    re.IGNORECASE,
)


def _try_capture_pending_action(step: Any) -> None:
    """
    If *step* is a (AgentAction, tool_output) pair whose output contains a
    WARNING preview, store the tool name + params in the asyncio ContextVar
    so that main.py can persist them to the session.
    """
    if not isinstance(step, (list, tuple)) or len(step) < 2:
        return
    tool_output_str = str(step[1])
    if not any(p in tool_output_str for p in _WARNING_PATTERNS):
        return
    action = step[0]
    tool_name = getattr(action, "tool", None)
    tool_input = getattr(action, "tool_input", None)
    if not tool_name or tool_input is None:
        return
    # tool_input may arrive as a JSON string from weaker LLMs — normalise to dict
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[Interceptor] tool_input is a non-JSON string — cannot capture pending action")
            return
    if not isinstance(tool_input, dict):
        try:
            tool_input = dict(tool_input)
        except (TypeError, ValueError):
            logger.warning("[Interceptor] Cannot convert tool_input to dict — cannot capture pending action")
            return
    clean_params = {k: v for k, v in tool_input.items() if k != "confirmed"}
    try:
        from backend.agents.context import set_pending_action
        set_pending_action({
            "tool": tool_name,
            "params": clean_params,
            "warning_text": tool_output_str,
        })
        logger.info(f"[Interceptor] Pending action captured: {tool_name} params={clean_params}")
    except Exception as ex:
        logger.warning(f"[Interceptor] Could not set pending action: {ex}")


# ── Public entry point ────────────────────────────────────────────────────────

def safe_agent_run(
    agent: AgentExecutor,
    tools: List[BaseTool],
    message: str,
    history: List[Any],
    is_list_query: bool = False,
) -> str:
    """
    Invoke the agent normally. If the output is raw tool-call JSON (the LLM
    described what to do instead of doing it), parse and execute the tool
    manually.

    Confirmed-write guard:
    - confirmed=False → call the tool for the preview response, return it
    - confirmed=True (or absent) → execute the tool and return the result

    On the next user turn (after preview), the agent will be re-invoked with
    confirmed=True already in the user message, so no extra state is needed.
    """
    try:
        result = agent.invoke({"input": message, "chat_history": history})
        output: str = result.get("output", "").strip()
    except Exception as e:
        logger.error(f"[Interceptor] agent.invoke failed: {e}", exc_info=True)
        return f"Agent error: {str(e)}"

    if not output:
        steps = result.get("intermediate_steps", [])
        if steps:
            last_step = steps[-1]
            last_tool_output = last_step[1] if isinstance(last_step, (list, tuple)) and len(last_step) >= 2 else last_step
            tool_output_str = str(last_tool_output)
            # If tool returned a WARNING, capture pending action and return it
            # directly so supervisor can detect it for confirmation routing
            if any(p in tool_output_str for p in _WARNING_PATTERNS):
                _try_capture_pending_action(last_step)
                logger.warning("[Interceptor] Tool returned WARNING — passing through directly.")
                return tool_output_str
            logger.warning("[Interceptor] output empty; returning last intermediate step result.")
            return tool_output_str

        # Last resort: try to extract tool call from the raw LLM messages
        # qwen2.5:7b sometimes puts tool calls in messages but not in output
        try:
            messages = result.get("messages", [])
            for msg in reversed(messages):
                content = getattr(msg, "content", "")
                if content:
                    tool_call = _extract_tool_call(str(content))
                    if tool_call and "name" in tool_call:
                        tool_name = tool_call["name"]
                        params = tool_call.get("parameters") or tool_call.get("arguments") or {}
                        tool = _find_tool(tool_name, tools)
                        if tool:
                            logger.warning(f"[Interceptor] Found tool call in messages: {tool_name}")
                            t0 = time.monotonic()
                            result = str(tool.invoke(params))
                            log_tool_call(logger, tool_name, params, result, (time.monotonic() - t0) * 1000)
                            return result
                # Check tool_calls attribute
                tool_calls = getattr(msg, "tool_calls", [])
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                        args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        if name:
                            tool = _find_tool(name, tools)
                            if tool:
                                logger.warning(f"[Interceptor] Found tool_call in message attr: {name}")
                                t0 = time.monotonic()
                                result = str(tool.invoke(args))
                                log_tool_call(logger, name, args, result, (time.monotonic() - t0) * 1000)
                                return result
        except Exception as ex:
            logger.error(f"[Interceptor] Message scan failed: {ex}", exc_info=True)

        return "Sorry, I could not process your request."

    # ── Detect raw tool-call JSON ─────────────────────────────────────────────
    tool_call = _extract_tool_call(output)
    if tool_call is None:
        steps = result.get("intermediate_steps", [])
        if steps:
            last_step = steps[-1]
            last_tool_output = last_step[1] if isinstance(last_step, (list, tuple)) and len(last_step) >= 2 else last_step
            tool_output_str = str(last_tool_output)
            if any(p in tool_output_str for p in _WARNING_PATTERNS):
                _try_capture_pending_action(last_step)
                return tool_output_str
            # ── List-query deterministic formatter ───────────────────────────
            if is_list_query:
                action = last_step[0] if isinstance(last_step, (list, tuple)) else None
                last_tool_name = getattr(action, "tool", None)
                if last_tool_name and last_tool_name in _FORMATTERS:
                    logger.info(f"[Interceptor] Formatting list output for tool '{last_tool_name}'")
                    return _FORMATTERS[last_tool_name](tool_output_str)
        # LLM hallucinated a WARNING without calling any tool — force a retry.
        if _HALLUCINATED_CONFIRM_RE.search(output) and not steps:
            logger.warning("[Interceptor] LLM hallucinated confirmation prompt without tool call — re-invoking with explicit directive.")
            forced_message = (
                f"CRITICAL: You MUST call the appropriate tool to handle this request. "
                f"Do NOT describe the action in text — invoke the tool function directly with confirmed=False. "
                f"Original request: {message}"
            )
            try:
                retry_result = agent.invoke({"input": forced_message, "chat_history": history})
                retry_output = retry_result.get("output", "").strip()
                retry_steps = retry_result.get("intermediate_steps", [])
                if retry_steps:
                    last_step = retry_steps[-1]
                    tool_output_str = str(last_step[1] if isinstance(last_step, (list, tuple)) and len(last_step) >= 2 else last_step)
                    if any(p in tool_output_str for p in _WARNING_PATTERNS):
                        _try_capture_pending_action(last_step)
                        return tool_output_str
                    return tool_output_str
                # Re-invocation also failed — strip prefix and return body
                cleaned = re.sub(r'^warning[!:]\s*', '', output, flags=re.IGNORECASE).lstrip()
                return cleaned or "I could not complete that action. Please try again with more specific phrasing."
            except Exception as e:
                logger.error(f"[Interceptor] Re-invocation failed: {e}", exc_info=True)
                return "I could not complete that action. Please try again."
        return output  # Normal text response

    tool_name: str = tool_call["name"]
    params: Dict[str, Any] = (
        tool_call.get("parameters")
        or tool_call.get("arguments")
        or {}
    )

    logger.warning(
        f"[Interceptor] Raw tool call intercepted: '{tool_name}' "
        f"params={params} — executing manually."
    )

    tool = _find_tool(tool_name, tools)
    if tool is None:
        logger.error(f"[Interceptor] Tool '{tool_name}' not found.")
        return f"I tried to call '{tool_name}' but it is not a known tool."

    # ── Execute (preview or real) ─────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        tool_result = tool.invoke(params)
        log_tool_call(logger, tool_name, params, str(tool_result), (time.monotonic() - t0) * 1000)
        return str(tool_result)
    except Exception as e:
        logger.error(f"[Interceptor] Tool '{tool_name}' failed: {e}", exc_info=True)
        return f"Tool '{tool_name}' failed: {str(e)}"
