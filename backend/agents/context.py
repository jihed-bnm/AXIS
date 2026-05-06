"""
Per-request context variables — asyncio-safe state shared between the agent
execution stack and the HTTP request handler without passing extra arguments
through every function in the call chain.

Uses Python's contextvars module (PEP 567), which is asyncio-task-safe.
FastAPI's sync endpoints also work correctly because each request runs in its
own synchronous execution context.
"""
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

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


# RAG context retrieved for the current exchange — set by specialists, read by main.py.
_rag_context_var: ContextVar[str] = ContextVar("rag_context", default="")


def set_rag_context(context: str) -> None:
    _rag_context_var.set(context)


def get_rag_context() -> str:
    return _rag_context_var.get()


def clear_rag_context() -> None:
    _rag_context_var.set("")


# Accumulated tool calls for the current exchange — appended by tool_interceptor,
# read and cleared by main.py.  Schema per entry: {"tool": str, "params": dict}.
_tool_calls_var: ContextVar[List[Dict[str, Any]]] = ContextVar("tool_calls", default=[])


def append_tool_call(call: Dict[str, Any]) -> None:
    current = list(_tool_calls_var.get())
    current.append(call)
    _tool_calls_var.set(current)


def get_tool_calls() -> List[Dict[str, Any]]:
    return list(_tool_calls_var.get())


def clear_tool_calls() -> None:
    _tool_calls_var.set([])
