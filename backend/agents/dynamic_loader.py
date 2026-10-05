"""
Dynamic agent loader — DISABLED.

All implementation is commented out. The four public API functions below are stubs
that return safe no-op values so every existing caller compiles and runs without error.
"""

# ── Public API stubs (dynamic agents disabled) ────────────────────────────────

def reload_dynamic_agents() -> int:
    """Stub — returns 0 (no agents loaded)."""
    return 0


def get_active_agents() -> dict:
    """Stub — returns empty registry."""
    return {}


def find_agent_for_message(message: str):
    """Stub — no agent matched."""
    return None


def run_dynamic_agent(agent_info: dict, message: str, history=None) -> str:
    """Stub — should never be reached while find_agent_for_message returns None."""
    return "Dynamic agents are currently disabled."


# ── Original implementation (commented out) ───────────────────────────────────
#
# from __future__ import annotations
#
# import builtins as _builtins
# import json as _json
# import logging
# import re
# from typing import Any, Dict, List, Optional
#
# from langchain.agents import AgentExecutor, create_tool_calling_agent
# from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
# from langchain_core.tools import tool as lc_tool
# from sqlalchemy import text as _sql_text
#
# from backend.agents.llm import get_llm
# from backend.models.database import get_session
# from backend.models.dynamic_agent_models import DynamicAgent
#
# logger = logging.getLogger(__name__)
#
# _SAFE_BUILTIN_NAMES = frozenset({
#     "None", "True", "False", "NotImplemented", "Ellipsis",
#     "int", "str", "float", "bool", "list", "dict", "tuple", "set", "bytes",
#     "len", "range", "enumerate", "zip", "map", "filter", "iter", "next",
#     "sorted", "reversed", "min", "max", "sum", "abs", "round", "divmod",
#     "isinstance", "issubclass", "hasattr", "getattr", "setattr",
#     "repr", "type", "object", "super", "property", "print",
#     "Exception", "ValueError", "TypeError", "KeyError", "AttributeError",
#     "IndexError", "RuntimeError", "StopIteration", "NotImplementedError",
#     "__build_class__",
# })
#
#
# def _build_exec_globals() -> dict:
#     safe_builtins = {
#         name: getattr(_builtins, name)
#         for name in _SAFE_BUILTIN_NAMES
#         if hasattr(_builtins, name)
#     }
#     return {
#         "__builtins__": safe_builtins,
#         "get_session": get_session,
#         "text": _sql_text,
#         "json": _json,
#     }
#
#
# def _strip_imports_and_decorator(code: str) -> str:
#     code = re.sub(r'^(?:from|import)\s+\S+.*$', '', code, flags=re.MULTILINE)
#     code = re.sub(r'^@tool\s*$', '', code, flags=re.MULTILINE)
#     return code.strip()
#
#
# _ACTIVE_AGENTS: Dict[str, dict] = {}
#
#
# def _patch_int_descriptions(tool_obj: Any) -> None:
#     schema_cls = getattr(tool_obj, 'args_schema', None)
#     if schema_cls is None:
#         return
#     pydantic_fields = getattr(schema_cls, '__fields__', None)
#     if pydantic_fields:
#         for fname, field in pydantic_fields.items():
#             try:
#                 if getattr(field, 'outer_type_', None) is int:
#                     fi = getattr(field, 'field_info', None)
#                     if fi is not None and not getattr(fi, 'description', None):
#                         fi.description = (
#                             f"Extract from user message — e.g. 'employee 1' → {fname}=1"
#                         )
#             except Exception:
#                 pass
#         return
#     model_fields_v2 = getattr(schema_cls, 'model_fields', None)
#     if model_fields_v2:
#         for fname, finfo in model_fields_v2.items():
#             try:
#                 if getattr(finfo, 'annotation', None) is int and not getattr(finfo, 'description', None):
#                     finfo.description = (
#                         f"Extract from user message — e.g. 'employee 1' → {fname}=1"
#                     )
#             except Exception:
#                 pass
#
#
# def _compile_lc_tool(tool_model: Any) -> Optional[Any]:
#     try:
#         clean_code = _strip_imports_and_decorator(tool_model.code_template)
#         namespace = _build_exec_globals()
#         exec(clean_code, namespace)
#         fn = namespace.get(tool_model.tool_name)
#         if fn is None or not callable(fn):
#             logger.warning("[DynamicLoader] '%s' not found after exec", tool_model.tool_name)
#             return None
#         compiled = lc_tool(fn)
#         _patch_int_descriptions(compiled)
#         return compiled
#     except Exception as exc:
#         logger.warning("[DynamicLoader] compile failed for '%s': %s", tool_model.tool_name, exc)
#         return None
#
#
# def _build_executor(agent_row: Any) -> Optional[tuple]:
#     lc_tools = []
#     for tool_model in agent_row.tools:
#         if not (tool_model.ast_validation_passed and tool_model.sandbox_test_passed):
#             continue
#         compiled = _compile_lc_tool(tool_model)
#         if compiled:
#             lc_tools.append(compiled)
#     if not lc_tools:
#         logger.warning("[DynamicLoader] '%s' has no valid tools — skipping", agent_row.name)
#         return None
#     llm = get_llm()
#     prompt = ChatPromptTemplate.from_messages([
#         ("system", agent_row.system_prompt),
#         MessagesPlaceholder(variable_name="chat_history", optional=True),
#         ("human", "{input}"),
#         MessagesPlaceholder(variable_name="agent_scratchpad"),
#     ])
#     agent = create_tool_calling_agent(llm, lc_tools, prompt)
#     executor = AgentExecutor(agent=agent, tools=lc_tools, verbose=False, max_iterations=5)
#     return executor, lc_tools
#
#
# def reload_dynamic_agents() -> int:
#     global _ACTIVE_AGENTS
#     db = get_session()
#     try:
#         active = (
#             db.query(DynamicAgent)
#             .filter(DynamicAgent.status == "active")
#             .all()
#         )
#         new_registry: Dict[str, dict] = {}
#         loaded = 0
#         for agent_row in active:
#             result = _build_executor(agent_row)
#             if result is None:
#                 continue
#             executor, lc_tools = result
#             keywords = (
#                 agent_row.keyword_rules
#                 if isinstance(agent_row.keyword_rules, list) else []
#             )
#             entry = {
#                 "agent_id":      agent_row.id,
#                 "agent_name":    agent_row.name,
#                 "system_prompt": agent_row.system_prompt,
#                 "executor":      executor,
#                 "lc_tools":      lc_tools,
#                 "keywords":      keywords,
#             }
#             for kw in keywords:
#                 new_registry[kw.lower()] = entry
#             loaded += 1
#             logger.info(
#                 "[DynamicLoader] Loaded '%s' (id=%d, %d keywords)",
#                 agent_row.name, agent_row.id, len(keywords),
#             )
#         _ACTIVE_AGENTS = new_registry
#         logger.info(
#             "[DynamicLoader] Registry ready — %d agent(s), %d keywords total",
#             loaded, len(new_registry),
#         )
#         return loaded
#     except Exception as exc:
#         logger.error("[DynamicLoader] reload failed: %s", exc, exc_info=True)
#         return 0
#     finally:
#         db.close()
#
#
# def get_active_agents() -> Dict[str, dict]:
#     return _ACTIVE_AGENTS
#
#
# def find_agent_for_message(message: str) -> Optional[dict]:
#     msg_lower = message.lower()
#     for keyword, entry in _ACTIVE_AGENTS.items():
#         if keyword in msg_lower:
#             return entry
#     return None
#
#
# def _try_direct_invoke(lc_tools: list, message: str) -> Optional[str]:
#     import re
#     numbers = re.findall(r'\b(\d+)\b', message)
#     if len(numbers) != 1:
#         return None
#     candidate = int(numbers[0])
#     for t in lc_tools:
#         schema_cls = getattr(t, 'args_schema', None)
#         if schema_cls is None:
#             continue
#         try:
#             schema = schema_cls.schema()
#         except Exception:
#             try:
#                 schema = schema_cls.model_json_schema()
#             except Exception:
#                 continue
#         props = schema.get('properties', {})
#         required = set(schema.get('required', list(props.keys())))
#         int_fields = [
#             name for name, info in props.items()
#             if info.get('type') == 'integer' and name in required
#         ]
#         if len(int_fields) == 1:
#             try:
#                 result = t.invoke({int_fields[0]: candidate})
#                 logger.info(
#                     "[DynamicAgent] Pre-pass: %s(%s=%d) succeeded",
#                     t.name, int_fields[0], candidate,
#                 )
#                 return str(result)
#             except Exception as exc:
#                 logger.warning("[DynamicAgent] Pre-pass invoke failed: %s", exc)
#     return None
#
#
# def run_dynamic_agent(agent_info: dict, message: str, history: list = None) -> str:
#     from langchain.agents import create_react_agent
#     from langchain_core.prompts import PromptTemplate
#
#     lc_tools = agent_info.get("lc_tools", [])
#
#     if not lc_tools:
#         llm = get_llm()
#         response = llm.invoke(f"{agent_info['system_prompt']}\n\nUser: {message}")
#         return response.content
#
#     direct = _try_direct_invoke(lc_tools, message)
#     if direct is not None:
#         return direct
#
#     tool_params_guide = "\n\nPARAMETER EXTRACTION GUIDE:\n"
#     for tool in lc_tools:
#         if hasattr(tool, "args_schema") and tool.args_schema:
#             schema = tool.args_schema.schema()
#             params = schema.get("properties", {})
#             tool_params_guide += f"\nFor {tool.name}:\n"
#             for param_name, param_info in params.items():
#                 param_type = param_info.get("type", "any")
#                 tool_params_guide += f"  - {param_name} ({param_type}): "
#                 if param_type == "integer":
#                     tool_params_guide += (
#                         "Extract numeric values from phrases like "
#                         "'employee 1' → 1, 'employee ID 5' → 5, 'for employee X' → X\n"
#                     )
#                 else:
#                     tool_params_guide += f"{param_info.get('description', 'value needed')}\n"
#
#     enhanced_system_prompt = agent_info["system_prompt"] + tool_params_guide + """
#
# CRITICAL INSTRUCTIONS:
# - Extract parameters from the user's message carefully.
# - "employee 1" means employee_id=1
# - "employee ID 5" means employee_id=5
# - "for employee X" means employee_id=X
# - If you have enough information from the message, call the tool immediately.
# - Only ask for clarification if the message truly lacks the required information."""
#
#     _react_base = PromptTemplate.from_template(
#         """{system_prompt}
#
# You have access to the following tools:
#
# {tools}
#
# Use the following format:
#
# Question: the input question you must answer
# Thought: you should always think about what to do
# Action: the action to take, should be one of [{tool_names}]
# Action Input: the input to the action
# Observation: the result of the action
# ... (this Thought/Action/Action Input/Observation can repeat N times)
# Thought: I now know the final answer
# Final Answer: the final answer to the original input question
#
# Begin!
#
# Question: {input}
# Thought:{agent_scratchpad}"""
#     )
#     full_prompt = PromptTemplate(
#         input_variables=["input", "tools", "tool_names", "agent_scratchpad"],
#         template=_react_base.template.replace("{system_prompt}", enhanced_system_prompt),
#     )
#
#     try:
#         agent = create_react_agent(get_llm(), lc_tools, full_prompt)
#         executor = AgentExecutor(
#             agent=agent,
#             tools=lc_tools,
#             verbose=True,
#             handle_parsing_errors=True,
#             max_iterations=5,
#             early_stopping_method="generate",
#         )
#         result = executor.invoke({"input": message})
#         return result.get("output", "I couldn't complete that request.")
#     except Exception as e:
#         logger.error("[DynamicAgent] Execution error: %s", e, exc_info=True)
#         return f"I encountered an error while processing your request: {str(e)}"
