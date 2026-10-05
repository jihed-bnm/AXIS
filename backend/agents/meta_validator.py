"""
Sandbox test runner for generated tool code.

Executes a generated tool function in an isolated exec() namespace with a
5-second timeout, synthetic parameters, and full exception capture.

AST validation (meta_agent._validate_tool_code) is the security gate.
This module is the runtime gate: does the function actually execute without
crashing against the live database?
"""
from __future__ import annotations

import builtins
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict

from sqlalchemy import text

from backend.models.database import get_session

logger = logging.getLogger(__name__)

_SANDBOX_TIMEOUT_SECONDS = 5

# Builtins safe to expose inside exec() — omits open, __import__, os, sys, etc.
_SAFE_BUILTIN_NAMES = frozenset({
    "None", "True", "False", "NotImplemented", "Ellipsis",
    "int", "str", "float", "bool", "list", "dict", "tuple", "set", "bytes",
    "len", "range", "enumerate", "zip", "map", "filter", "iter", "next",
    "sorted", "reversed", "min", "max", "sum", "abs", "round", "divmod",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "repr", "type", "object", "super", "property", "print",
    "Exception", "ValueError", "TypeError", "KeyError", "AttributeError",
    "IndexError", "RuntimeError", "StopIteration", "NotImplementedError",
    "__build_class__",
})


def _build_sandbox_globals() -> dict:
    """Fresh exec() globals per call: safe builtins + project deps only."""
    safe_builtins = {
        name: getattr(builtins, name)
        for name in _SAFE_BUILTIN_NAMES
        if hasattr(builtins, name)
    }
    return {
        "__builtins__": safe_builtins,
        "get_session": get_session,
        "text": text,
        "json": json,
    }


def _strip_imports_and_decorator(code: str) -> str:
    """
    Remove import lines and @tool decorator from generated code.

    The sandbox namespace pre-seeds get_session / text / json, so the import
    statements are redundant — and __import__ is not in the restricted
    builtins, so they would raise NameError if left in.
    """
    code = re.sub(r'^(?:from|import)\s+\S+.*$', '', code, flags=re.MULTILINE)
    code = re.sub(r'^@tool\s*$', '', code, flags=re.MULTILINE)
    return code.strip()


def _generate_test_params(parameters_schema: Dict[str, Any]) -> dict:
    """
    Build minimal synthetic params: one plausible value per entry in the
    schema dict {param_name: {type, description}}.
    """
    params: dict = {}
    for param_name, param_info in parameters_schema.items():
        param_type = param_info.get("type", "str").lower()

        if param_type in ("integer", "int"):
            params[param_name] = 1
        elif param_type == "float":
            params[param_name] = 1.0
        elif param_type in ("boolean", "bool"):
            params[param_name] = True
        else:
            name_lower = param_name.lower()
            if "status" in name_lower:
                params[param_name] = "active"
            elif "date" in name_lower:
                params[param_name] = "2026-01-01"
            elif "email" in name_lower:
                params[param_name] = "test@example.com"
            elif "name" in name_lower:
                params[param_name] = "Test"
            else:
                params[param_name] = "test"

    return params


def test_tool_in_sandbox(
    tool_code: str,
    tool_name: str,
    parameters_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute generated tool code safely and return a structured test report.

    Args:
        tool_code:          Full Python source of the generated tool (as
                            produced by _assemble_tool_code in meta_agent.py).
        tool_name:          Name of the function to call after exec().
        parameters_schema:  {param_name: {"type": str, "description": str}}

    Returns:
        {
            "passed":      bool,
            "output":      str,        # tool's return value (capped at 1 000 chars)
            "error":       str | None,
            "duration_ms": int,
            "test_params": dict,       # synthetic args used for the call
        }
    """
    test_params = _generate_test_params(parameters_schema)
    clean_code = _strip_imports_and_decorator(tool_code)

    namespace = _build_sandbox_globals()

    # Phase 1: compile the function definition into the namespace
    try:
        exec(clean_code, namespace)  # noqa: S102 — intentional restricted sandbox
    except Exception as exc:
        logger.warning("[Sandbox] exec() failed for '%s': %s", tool_name, exc)
        return {
            "passed":      False,
            "output":      "",
            "error":       f"exec() failed: {type(exc).__name__}: {exc}",
            "duration_ms": 0,
            "test_params": test_params,
        }

    fn = namespace.get(tool_name)
    if fn is None:
        return {
            "passed":      False,
            "output":      "",
            "error":       f"Function '{tool_name}' not found in namespace after exec().",
            "duration_ms": 0,
            "test_params": test_params,
        }

    # Phase 2: call the function under a timeout
    start = time.monotonic()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, **test_params)
        try:
            output = future.result(timeout=_SANDBOX_TIMEOUT_SECONDS)
            duration_ms = int((time.monotonic() - start) * 1000)
        except FuturesTimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("[Sandbox] '%s' timed out after %ds", tool_name, _SANDBOX_TIMEOUT_SECONDS)
            return {
                "passed":      False,
                "output":      "",
                "error":       f"Execution timed out after {_SANDBOX_TIMEOUT_SECONDS}s.",
                "duration_ms": duration_ms,
                "test_params": test_params,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("[Sandbox] '%s' raised %s: %s", tool_name, type(exc).__name__, exc)
            return {
                "passed":      False,
                "output":      "",
                "error":       f"{type(exc).__name__}: {exc}",
                "duration_ms": duration_ms,
                "test_params": test_params,
            }

    if not isinstance(output, str):
        return {
            "passed":      False,
            "output":      repr(output),
            "error":       f"Tool returned {type(output).__name__!r}, expected str.",
            "duration_ms": duration_ms,
            "test_params": test_params,
        }

    logger.info(
        "[Sandbox] '%s' passed in %dms — output: %s",
        tool_name, duration_ms, output[:120],
    )
    return {
        "passed":      True,
        "output":      output[:1000],
        "error":       None,
        "duration_ms": duration_ms,
        "test_params": test_params,
    }
