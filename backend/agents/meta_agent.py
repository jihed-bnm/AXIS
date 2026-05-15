"""
Meta-Agent — generates new specialized ERP agents from a business description.

Workflow:
  1. Caller provides a plain-English domain description ("employee leave management").
  2. The agent calls introspect_schema() to read live DB tables/columns.
  3. Based on that, it produces a JSON spec: agent name, system prompt, keyword
     rules, and a list of read-only SQL tools (each with a query + parameters).
  4. This module assembles safe Python tool code from those specs, runs AST +
     safety validation, and persists everything to dynamic_agents /
     generated_tools tables.
  5. Returns a structured result dict the API can forward to the caller.

Design rationale for template-based code generation
----------------------------------------------------
Having the LLM embed Python code inside a JSON string causes systematic
escaping failures with qwen2.5:7b.  Instead the LLM outputs a *data* spec
(SQL query + parameter list) and this module assembles the Python function
from a server-side template.  The template enforces every CLAUDE.md safety
invariant (get_session, try/finally, parameterized queries) so there is no
way for the LLM to inject unsafe constructs.
"""
from __future__ import annotations

import ast
import concurrent.futures
import json
import logging
import re
from typing import Any, Dict, List, Optional

from backend.agents.llm import get_llm
from backend.models.database import get_session
from backend.models.dynamic_agent_models import DynamicAgent, GeneratedTool
from backend.tools.meta_tools.introspect_schema import introspect_schema

logger = logging.getLogger(__name__)

# ── SQL safety ────────────────────────────────────────────────────────────────

# Any of these keywords in a generated SQL string means the tool is mutating.
_SQL_MUTATION_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE)\b',
    re.IGNORECASE,
)

# Python constructs that must never appear in generated code.
_DANGEROUS_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open",
    "os", "sys", "subprocess", "importlib", "shutil",
    "socket", "urllib", "requests", "httpx",
})

# ── Code template ─────────────────────────────────────────────────────────────

# The LLM supplies: tool_name, description, sql_query, parameters (list of
# {name, type, description}).  This template wraps them in the project-standard
# @tool pattern.  Placeholders: {name} {description} {params_sig}
#                                {params_bind} {sql}
_CODE_TEMPLATE = '''\
from langchain_core.tools import tool
from sqlalchemy import text
from backend.models.database import get_session


@tool
def {name}({params_sig}) -> str:
    """{description}"""
    db = get_session()
    try:
        rows = db.execute(
            text("{sql}"),
            {{{params_bind}}},
        ).fetchall()
        if not rows:
            return "No records found."
        keys = list(rows[0]._mapping.keys())
        return "\\n".join(str(dict(zip(keys, row))) for row in rows)
    finally:
        db.close()
'''

# Python type string → function-signature annotation
_TYPE_MAP: Dict[str, str] = {
    "integer": "int",
    "int":     "int",
    "string":  "str",
    "str":     "str",
    "float":   "float",
    "boolean": "bool",
    "bool":    "bool",
    "date":    "str",
    "text":    "str",
}

# ── System prompt ─────────────────────────────────────────────────────────────

META_AGENT_SYSTEM_PROMPT = """\
You are an expert AI system architect that generates specialized business \
agents for an ERP system built on PostgreSQL.

When given a business domain description (e.g. "employee leave management", \
"inventory tracking", "project milestone tracking"), you generate a complete \
agent specification.

YOUR WORKFLOW:
1. Call introspect_schema() FIRST — read every table, column, and foreign key.
2. Identify which tables are relevant to the requested domain.
3. Design 2-5 read-only SQL queries that would be genuinely useful for that domain.
4. Emit the agent specification as the JSON format below.

OUTPUT FORMAT — respond with ONLY valid JSON, no preamble, no markdown fences:
{{
  "agent_name": "HR Management Agent",
  "description": "Handles employee leave requests, balances, and HR reporting.",
  "system_prompt": "You are an HR specialist agent...",
  "keyword_rules": ["employee", "leave", "vacation", "sick", "HR", "absence"],
  "tools": [
    {{
      "name": "get_employee_leaves",
      "description": "Lists leave requests for an employee filtered by status.",
      "sql": "SELECT id, leave_type, start_date, end_date, days, status FROM leave_requests WHERE employee_id = :employee_id",
      "parameters": [
        {{"name": "employee_id", "type": "integer", "description": "Database ID of the employee"}}
      ]
    }}
  ]
}}

STRICT RULES FOR SQL QUERIES:
- SELECT queries ONLY.  No INSERT, UPDATE, DELETE, DROP, or any mutation.
- Use named bind parameters (:param_name) — NEVER string formatting.
- Only reference tables and columns that actually exist in the schema \
  (you just read it with introspect_schema).
- Keep queries simple: one main table, up to two JOINs.

RULES FOR keyword_rules:
- 6-12 lowercase keywords/phrases that a user would type to reach this agent.
- Must be specific enough not to collide with CRM / Invoicing / Chart modules.

RULES FOR system_prompt:
- 3-6 sentences in second-person ("You are a ...").
- State the domain, the available actions, and remind the agent to call tools \
  rather than guessing from context.

Do NOT output any text before or after the JSON object.\
"""

# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Three-strategy extractor — handles LLM responses that wrap JSON in markdown
    fences, add preamble text, or emit it bare.
    """
    # Strategy 1: bare JSON
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: ```json ... ``` or ``` ... ```
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: first balanced { ... } block in the text
    depth, start = 0, None
    in_string, escape_next = False, False
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
                try:
                    return json.loads(text[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    break
    return None


# ── Code assembly ─────────────────────────────────────────────────────────────

def _assemble_tool_code(tool_spec: Dict[str, Any]) -> str:
    """
    Build Python tool source from the LLM's data spec and the fixed template.
    The LLM never writes Python — it only writes the SQL and parameter names.
    """
    name   = tool_spec["name"]
    desc   = tool_spec.get("description", "").replace('"', "'")
    sql    = tool_spec["sql"].replace('"', "'").strip()
    params = tool_spec.get("parameters", [])

    # Build function signature and SQLAlchemy bind dict
    sig_parts  = []
    bind_parts = []
    for p in params:
        py_type = _TYPE_MAP.get(p.get("type", "str"), "str")
        sig_parts.append(f"{p['name']}: {py_type}")
        bind_parts.append(f'"{p["name"]}": {p["name"]}')

    params_sig  = ", ".join(sig_parts)
    params_bind = ", ".join(bind_parts)

    return _CODE_TEMPLATE.format(
        name=name,
        description=desc,
        params_sig=params_sig,
        params_bind=params_bind,
        sql=sql,
    )


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_tool_code(code: str, sql: str) -> tuple[bool, str]:
    """
    Run two validation passes:
      1. AST parse — catches syntax errors and dangerous constructs.
      2. SQL safety — confirms no mutation keywords in the SQL string.

    Returns (passed: bool, log: str).
    """
    log_lines: List[str] = []

    # Pass 1: AST syntax
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"

    log_lines.append("AST parse: OK")

    # Pass 1b: walk for dangerous names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _DANGEROUS_NAMES:
            return False, f"Forbidden name '{node.id}' found in generated code."
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in getattr(node, 'names', []):
                mod = alias.name.split('.')[0]
                if mod in _DANGEROUS_NAMES:
                    return False, f"Forbidden import '{alias.name}' found."

    log_lines.append("AST safety scan: OK (no dangerous names or imports)")

    # Pass 2: SQL mutation check
    if _SQL_MUTATION_KEYWORDS.search(sql):
        found = _SQL_MUTATION_KEYWORDS.search(sql).group(0)
        return False, f"SQL mutation keyword '{found}' detected — only SELECT is allowed."

    log_lines.append("SQL safety check: OK (SELECT only)")

    # Pass 3: compile() — catches issues ast.parse() misses in some edge cases
    try:
        compile(code, "<generated>", "exec")
    except Exception as exc:
        return False, f"compile() failed: {exc}"

    log_lines.append("compile(): OK")
    return True, "\n".join(log_lines)


# ── DB persistence ────────────────────────────────────────────────────────────

def _persist_agent_spec(
    spec: Dict[str, Any],
    created_by: Optional[int],
) -> Dict[str, Any]:
    """
    Validate and persist the agent spec to dynamic_agents + generated_tools.
    Returns a summary dict (no ORM objects — safe to JSON-serialise).
    """
    db = get_session()
    try:
        # Check for name collision
        existing = (
            db.query(DynamicAgent)
            .filter(DynamicAgent.name == spec["agent_name"])
            .first()
        )
        if existing:
            return {
                "status":  "error",
                "message": f"An agent named '{spec['agent_name']}' already exists (id={existing.id}).",
            }

        # Validate and assemble each tool
        tool_rows = []
        test_results: Dict[str, Any] = {"tools": []}

        for tool_spec in spec.get("tools", []):
            code    = _assemble_tool_code(tool_spec)
            sql     = tool_spec.get("sql", "")
            passed, test_log = _validate_tool_code(code, sql)

            tool_rows.append(GeneratedTool(
                tool_name              = tool_spec["name"],
                description            = tool_spec.get("description", ""),
                code_template          = code,
                parameters_schema      = {
                    p["name"]: {
                        "type":        p.get("type", "str"),
                        "description": p.get("description", ""),
                    }
                    for p in tool_spec.get("parameters", [])
                },
                ast_validation_passed  = passed,
                sandbox_test_passed    = False,  # runtime test done at activation
                test_log               = test_log,
            ))
            test_results["tools"].append({
                "name":   tool_spec["name"],
                "passed": passed,
                "log":    test_log,
            })

        all_passed = all(t["passed"] for t in test_results["tools"])
        test_results["all_tools_passed"] = all_passed

        agent_row = DynamicAgent(
            name          = spec["agent_name"],
            description   = spec.get("description", ""),
            system_prompt = spec.get("system_prompt", ""),
            keyword_rules = spec.get("keyword_rules", []),
            status        = "draft",
            created_by    = created_by,
            test_results  = test_results,
        )

        for t in tool_rows:
            agent_row.tools.append(t)

        db.add(agent_row)
        db.commit()
        db.refresh(agent_row)

        logger.info(
            "[MetaAgent] Persisted '%s' (id=%d) — %d tools, all_passed=%s",
            agent_row.name, agent_row.id, len(tool_rows), all_passed,
        )

        return {
            "status":        "created",
            "agent_id":      agent_row.id,
            "agent_name":    agent_row.name,
            "description":   agent_row.description,
            "tool_count":    len(tool_rows),
            "all_valid":     all_passed,
            "test_results":  test_results,
            "db_status":     agent_row.status,
            "message": (
                f"Agent '{agent_row.name}' saved as draft with {len(tool_rows)} tool(s). "
                + ("All tools passed validation." if all_passed
                   else "Some tools failed validation — review test_results before activating.")
            ),
        }

    except Exception as exc:
        db.rollback()
        logger.error("[MetaAgent] DB persistence failed: %s", exc, exc_info=True)
        return {"status": "error", "message": f"Database error: {exc}"}
    finally:
        db.close()


# ── Schema filtering ─────────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "for", "and", "or", "but", "in", "on", "at", "to",
    "from", "with", "by", "of", "create", "agent", "managing", "tracking",
    "management", "system", "handle", "handles", "based", "using", "that",
    "this", "its", "their", "which", "about", "new", "all", "my",
})

_ALWAYS_INCLUDE = frozenset({"users", "companies"})


def _filter_relevant_schema(full_schema: str, domain_description: str) -> str:
    """
    Return a schema JSON string containing only tables relevant to the domain.

    Matching strategy:
      1. Tokenise the domain description, drop stop-words.
      2. Keep any table whose name contains at least one remaining keyword.
      3. Always include ``users`` and ``companies`` (common FK targets).
      4. Fallback: if nothing matched, keep the first 5 tables so the prompt
         is never empty.

    Reduces a 32-table / 41 KB schema to 3-6 tables / ~3-5 KB, which fits
    comfortably in a qwen2.5:7b context window.
    """
    schema_dict = json.loads(full_schema)
    all_tables  = schema_dict.get("tables", {})

    keywords = {
        w for w in domain_description.lower().split()
        if w not in _STOP_WORDS and len(w) > 2
    }

    relevant: dict = {}
    for table_name, table_info in all_tables.items():
        if table_name in _ALWAYS_INCLUDE:
            relevant[table_name] = table_info
        elif any(kw in table_name.lower() for kw in keywords):
            relevant[table_name] = table_info

    if not relevant:
        relevant = dict(list(all_tables.items())[:5])

    return json.dumps({"tables": relevant, "table_count": len(relevant)}, indent=2)


# ── Public entry point ────────────────────────────────────────────────────────

def run_meta_agent(
    domain_description: str,
    created_by: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate, validate, and persist a new specialist agent.

    Args:
        domain_description:  Plain-English domain description, e.g.
                             "employee leave management and HR reporting".
        created_by:          User ID of the requester (nullable).

    Returns a dict with keys:
        status        — "created" | "error"
        agent_id      — int (on success)
        agent_name    — str
        tool_count    — int
        all_valid     — bool
        test_results  — dict
        message       — human-readable summary
    """
    print("[MetaAgent] Starting agent generation...")
    logger.info("[MetaAgent] Received request: %r", domain_description)

    # Step 1: fetch live schema then filter to relevant tables only
    print("[MetaAgent] Fetching database schema...")
    try:
        full_schema: str = introspect_schema.invoke({})
    except Exception as exc:
        logger.error("[MetaAgent] introspect_schema failed: %s", exc, exc_info=True)
        print(f"[MetaAgent] ERROR: Schema introspection failed: {exc}")
        return {"status": "error", "message": f"Schema introspection failed: {exc}"}
    print(f"[MetaAgent] Full schema loaded ({len(full_schema)} chars)")

    print("[MetaAgent] Filtering schema to relevant tables...")
    schema_json = _filter_relevant_schema(full_schema, domain_description)
    n_tables = json.loads(schema_json).get("table_count", 0)
    print(f"[MetaAgent] Filtered schema ({len(schema_json)} chars, {n_tables} tables)")

    # Step 2: build a single self-contained prompt
    print("[MetaAgent] Building generation prompt...")
    prompt = (
        f"{META_AGENT_SYSTEM_PROMPT}\n\n"
        f"DATABASE SCHEMA (relevant tables only):\n{schema_json}\n\n"
        f"DOMAIN REQUEST:\n{domain_description}\n\n"
        f"Generate the agent specification as JSON:"
    )
    print(f"[MetaAgent] Prompt built ({len(prompt)} chars)")

    # Step 3: call LLM with a 120-second timeout
    print("[MetaAgent] Calling LLM (timeout: 120 seconds)...")
    llm = get_llm()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(llm.invoke, prompt)
        try:
            response = future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            print("[MetaAgent] LLM call timed out after 120 seconds")
            return {
                "status":  "error",
                "message": "LLM generation timed out. Try a simpler domain description.",
                "raw":     "",
            }
        except Exception as exc:
            logger.error("[MetaAgent] LLM call failed: %s", exc, exc_info=True)
            print(f"[MetaAgent] ERROR: LLM call failed: {exc}")
            return {"status": "error", "message": f"LLM call failed: {exc}"}
    raw_output: str = response.content
    print(f"[MetaAgent] LLM response received ({len(raw_output)} chars)")
    logger.debug("[MetaAgent] Raw LLM output: %s", raw_output[:500])

    # Step 4: extract JSON from response
    print("[MetaAgent] Extracting JSON...")
    spec = _extract_json(raw_output)
    if spec is None:
        logger.error("[MetaAgent] Could not extract JSON from output:\n%s", raw_output)
        print("[MetaAgent] ERROR: Could not extract valid JSON from LLM output")
        print(f"[MetaAgent] Raw output preview: {raw_output[:300]}")
        return {
            "status":  "error",
            "message": "LLM did not return valid JSON. Raw output stored in logs.",
            "raw":     raw_output[:2000],
        }
    print(f"[MetaAgent] JSON extracted — agent_name={spec.get('agent_name', '?')}, tools={len(spec.get('tools', []))}")

    # Minimal field validation before touching the DB
    print("[MetaAgent] Validating tools...")
    for required in ("agent_name", "tools", "keyword_rules"):
        if required not in spec:
            print(f"[MetaAgent] ERROR: Missing required field '{required}'")
            return {
                "status":  "error",
                "message": f"Agent spec is missing required field '{required}'.",
                "spec":    spec,
            }

    if not isinstance(spec["tools"], list) or len(spec["tools"]) == 0:
        print("[MetaAgent] ERROR: Spec contains no tools")
        return {
            "status":  "error",
            "message": "Agent spec must include at least one tool.",
            "spec":    spec,
        }
    print(f"[MetaAgent] {len(spec['tools'])} tool(s) defined")

    # Step 5: validate tool code and persist to DB
    print("[MetaAgent] Persisting to database...")
    result = _persist_agent_spec(spec, created_by)
    if result.get("status") == "created":
        print(f"[MetaAgent] Agent created successfully — '{result['agent_name']}' (id={result['agent_id']}, all_valid={result['all_valid']})")
    else:
        print(f"[MetaAgent] ERROR during persistence: {result.get('message')}")
    return result
