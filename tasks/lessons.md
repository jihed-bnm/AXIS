# Project Lessons

## Shell / Tooling

**Lesson (2026-04-13): Never use `python -c` for multi-line diagnostics on Windows.**
Claude Code's shell guard blocks any command containing `#` inside quoted strings (interprets it as potential argument hiding) and will loop on approval prompts. Always use a throwaway `.py` file in the project root, run with `python <filename>.py`, then delete when done. Applies to all multi-line Python diagnostics — anything longer than ~2 lines.

## Prompts / LLM Behavior

**Lesson (2026-04-13): Template examples in system prompts cause qwen2.5:7b to pattern-complete instead of calling tools.**
The `OUTPUT FORMAT FOR LIST RESPONSES` block with pipe-separated field examples (`[ID] Name | Role | Company | Email`) caused the model to fabricate responses directly from the template without invoking any tool. Fix: replace with a procedure-anchored `RECORD FORMAT` block containing no field examples. The formatter layer in `tool_interceptor.py` owns field order — not the prompt.

**Lesson (2026-04-13): `TOOL_CALL_ENFORCEMENT` must be the last line of every specialist prompt.**
qwen2.5:7b has a recency bias — the last instruction in the system prompt has the strongest effect. Moving `TOOL_CALL_ENFORCEMENT` to the final line (after `CONFIRMATION_SYSTEM`) measurably improved tool-call compliance.

## Architecture

**Lesson (2026-04-13): RAG context is harmful for generic list queries.**
The retriever for "list invoices" returns the 5 nearest invoice vectors — whichever company happens to cluster near the query embedding. The model treats those as the target company and filters the tool call. Fix: add `LIST_INTENTS` fast-path that bypasses the retriever for generic list queries, mirroring the pattern already established in `crm_specialist.py`. As of 2026-04-13, CRM, Invoice, and Chart all have this guard. Three copies — do not abstract into a shared helper until a fourth use case arises.

**Lesson (2026-04-13): Deterministic list formatting belongs in the interceptor, not the prompt.**
Putting field-order templates in prompts is fragile (model ignores or embellishes them). The `_FORMATTERS` dict in `tool_interceptor.py` owns field order for list tools. The hook fires after `AgentExecutor` finishes (not mid-loop), so multi-step chains still see structured tool returns and the LLM's synthesis is only bypassed for the final user-facing output of list queries.

---

## Appended Lessons (2026-04-13)

**Lesson: Never put rendered output examples in prompts for small models.**
qwen2.5:7b (and likely any sub-14B model) treats filled-in templates like `[ID] Name | Role | Company` as completion targets and will fabricate data matching the shape rather than calling tools. Rule: describe output format procedurally, never visually. If deterministic rendering is needed, do it in code post-tool-execution, not via prompt instruction.

**Lesson: Tool-calling instructions belong at the absolute end of the system prompt.**
Small models have strong recency bias. Burying enforcement rules mid-prompt or inside bullet lists makes them functionally invisible. The `TOOL_CALL_ENFORCEMENT` line must be the last thing the model sees before the user message.

**Lesson: RAG context is harmful for generic list queries.**
Retrievers return nearest-neighbor matches by embedding similarity, which for queries like "list invoices" is essentially noise (~0.4 cosine). The model treats those near-random results as the answer set. Rule: list-intent queries must bypass the retriever entirely. Maintain a per-agent `LIST_INTENTS` set and route around RAG when matched.

**Lesson: Never use `python -c` for multi-line diagnostics on Windows.**
Claude Code's shell guard blocks any command containing `#` inside quoted strings and loops on approval prompts. Always use a throwaway `.py` file in the project root, run with `python <filename>.py`, then delete it when done.

**Lesson: Short-query routing in multi-agent supervisors must use conversational context, not just the current message.**
A 3-letter user reply to a clarifying question has no meaningful routing signal on its own — "BNA" after "did you mean BNA or BAN?" is obviously CRM, but stateless routing on the bare string classifies it as GENERAL. The fix: before falling to the LLM router, inspect whether the previous assistant turn asked a disambiguation question. If both conditions are true (CRM tag AND disambiguation phrase in last response), route to CRM. This pattern applies to any specialist that asks clarifying questions whose answers are short or content-free.

**Lesson: Scratch tests prove isolation, not integration. Only a live POST /chat trace closes a bug.**
A scratch `.py` file that calls a tool or formatter directly confirms the component works in isolation. It does not confirm the integrated path (supervisor → specialist → tool → formatter → response) works. A bug is not "fixed" until a live trace through `POST /chat` shows the correct output. If that step is skipped, the fix is unverified regardless of scratch pass rate — and a stale UI observation may be the only signal of the real failure.

**Lesson: When routing logic depends on conversational history, use `next(iterator, default)` with a safe default (empty string, not None) so downstream string operations work without null guards.**
Avoids a class of first-turn-of-session crashes without adding defensive branching. Example: `last_assistant = next((e["content"] for e in reversed(history) if e.get("role") == "assistant"), "")` — `"".strip().startswith(…)` is always safe; `None.strip()` is not.

**Lesson: Normalization logic written in one place will usually need to exist in other places too.**
When writing normalization in one location (e.g., a data cleanup migration like `cleanup_companies.sql`), flag the other locations that will eventually need the same logic — ingest guards, ETL dedup, runtime validation — even if you don't fix them today. If the same normalization exists in 3+ places, extract to a shared utility module (e.g., `utils/normalization.py`). The `_normalize_company_name` function currently lives in `data/populate_operational.py` and mirrors logic in `cleanup_companies.sql`; the ETL dedup in `airflow/dags/etl_jbm_pipeline.py:460` is a third location that will eventually need the same treatment.

**Lesson: Normalization character sets must be kept in sync across all sites.**
When data cleaning logic exists in multiple places (SQL migration + Python ingest guard + potentially ETL dedup), any change to the character set or normalization rules must be applied to ALL sites in the same change. Drift between sites silently re-introduces the bug the cleanup was meant to fix. Before modifying one normalization site, grep for related sites and update them together. In this project: `_normalize_company_name()` in `data/populate_operational.py` and the `REGEXP_REPLACE` in `cleanup_companies.sql` must always use the same character class. Current set as of 2026-04-16: `[*#!@]` — sourced from `generate_raw_data.py:168` and `:791`.

**lesson: server issues**
Always hard-kill the server when changing agents/prompts; --reload is unreliable. AgentExecutor instances are cached as module-level globals. --reload recompiles source files but does not always re-initialize module-level state, so prompt and tool definition changes can fail to reach the LLM even after the file is on disk. The reliable restart sequence on Windows: for /f "tokens=5" %a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %a, then start without --reload. This single mistake produced a 90-minute debug session where Claude Code's direct-invocation tests passed, the file edits were correct, but frontend tests failed — purely because the frontend was hitting a cached agent instance from before the prompt edit.