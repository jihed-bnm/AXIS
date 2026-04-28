"""
Per-request context variables — asyncio-safe state shared between the agent
execution stack and the HTTP request handler without passing extra arguments
through every function in the call chain.

Uses Python's contextvars module (PEP 567), which is asyncio-task-safe.
FastAPI's sync endpoints also work correctly because each request runs in its
own synchronous execution context.
"""
from contextvars import ContextVar
from typing import Any, Dict, Optional

# Holds tool-call metadata when an agent returns a WARNING preview (confirmed=False).
# Set by tool_interceptor.safe_agent_run when it detects a WARNING in the tool output.
# Read and cleared by main.py at the end of each request handler.
#
# Schema: {"tool": str, "params": dict}
# "params" never contains "confirmed" — the caller always adds confirmed=True.
_pending_action_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "pending_action", default=None
)


def set_pending_action(action: Dict[str, Any]) -> None:
    _pending_action_var.set(action)


def get_pending_action() -> Optional[Dict[str, Any]]:
    return _pending_action_var.get()


def clear_pending_action() -> None:
    _pending_action_var.set(None)
