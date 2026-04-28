# CLAUDE.md — Source of Truth

This file is the authoritative guide for Claude Code when working in this repository. Follow it exactly.

## Project Overview

ERP AI Agent — FastAPI backend + LangChain multi-agent orchestration + PostgreSQL + pgvector/ChromaDB RAG + single-file HTML frontend. Users chat through `POST /chat`, which routes to specialist agents (CRM, Invoicing, Chart).

Currency is **TND** everywhere. Today's reference date: 2026-04-13.

---

## 1. Architecture — Core Patterns (MUST follow)

### 1.1 Request flow
```
POST /chat → Supervisor (keyword → LLM fallback) → Specialist Agent → @tool → DB
                                                        ↑
                                              RAG context injected
```

### 1.2 Two-tier routing (`backend/agents/supervisor.py`)
- **Tier 1**: deterministic keyword match in `KEYWORD_RULES` / chart keywords. Cheap, no LLM.
- **Tier 2**: Ollama `qwen2.5:7b` router only when Tier 1 returns `None`.
- Valid modules: `CRM`, `INVOICING`, `CHART`, `GENERAL`. Nothing else.

### 1.3 Specialist agents
| Module | File | Tools module |
|---|---|---|
| CRM | `backend/agents/crm_specialist.py` | `backend/tools/crm_tools.py` |
| Invoicing | `backend/agents/invoice_specialist.py` | `backend/tools/invoice_tools.py` |
| Chart | `backend/agents/chart_agent.py` | `backend/tools/chart_tools.py` |

Each specialist is built with `create_tool_calling_agent` + `AgentExecutor` and wrapped by `safe_agent_run` (`backend/agents/tool_interceptor.py`).

### 1.3a LLM factory (`backend/agents/llm.py`)
- All agents **must** import the LLM via `from backend.agents.llm import get_llm`.
- The model name lives in `ERP_MODEL` inside `llm.py` — change it there only.
- `OllamaEmbeddings` (RAG) is separate from `ChatOllama` (agents) and lives in `backend/rag/`.

### 1.3b Audit logging (`backend/utils/audit.py`)
- Every write tool **must** call `log_action(db, action, entity, entity_id, payload, result)` from `backend/utils/audit.py` after a confirmed mutation.
- Do not define `log_action` locally in any tool file.

### 1.3c Shared prompt scaffold (`backend/agents/prompt_parts.py`)
- Shared rules (TND formatting, language, tool enforcement, output tag, confirmation system) live here as string constants.
- Specialist `SYSTEM_PROMPT`s are f-strings that compose domain rules + shared constants.
- Add a constant here **only** if it appears in two or more specialist prompts. Domain-specific rules stay in the specialist file.

### 1.4 Tool pattern
- All tools are LangChain `@tool` functions in `backend/tools/`.
- **READ** tools execute directly and return formatted text.
- **WRITE** tools use two-phase confirmation:
  1. `confirmed=False` → return a preview string.
  2. `confirmed=True` → execute + write to `AuditLog` via `log_action()` from `backend/utils/audit.py`.
- Every DB session is opened via `get_session()` (from `backend/models/database.py`) and closed in `try/finally db.close()`.
- `get_db()` in `database.py` is the FastAPI `Depends()` generator — only use it with `Depends()`. Use `get_session()` everywhere else.

### 1.5 RAG injection
- Embeddings: `nomic-embed-text` via Ollama (768-dim), stored in ChromaDB at `./chroma_db/`.
- Collections: `jbm_crm`, `jbm_invoicing` (cosine).
- Source: warehouse tables **only** (`warehouse.*`), never operational tables.
- Retriever: `ERPRetriever` in `backend/rag/retriever.py`. Specialists prepend top-5 (+ company-specific) context before agent invocation.

### 1.6 Session & errors
- `/chat` stores last 20 messages per session on the `Session` model.
- Errors must use `backend/error_handler.py` (`ERPErrorType`, `handle_agent_error`, `validate_user_input`). Do not raise raw exceptions to the user.

### 1.7 Data layer
- SQLAlchemy ORM, tables auto-created at startup via `Base.metadata.create_all()`.
- Only CRM + Invoicing models load at startup.
- Warehouse schema is populated by ETL (`backend/etl/run_etl.py` or Airflow DAG `jbm_etl_pipeline`).

---

## 2. Anti-Patterns — STOP doing these

These are specific behaviors to eliminate. If you catch yourself about to do one, stop.

1. **Do not duplicate tools.** If a capability exists in `crm_tools.py` or `invoice_tools.py`, extend it — do not create a parallel `*_v2`, `*_new`, or inline helper.
2. **Do not bypass the two-phase write pattern.** Every mutating tool must support `confirmed=False` preview. No direct-execute shortcut "just this once".
3. **Do not add new routing tiers or alternate routers.** Extend `KEYWORD_RULES` or the LLM router prompt in `supervisor.py`. No custom per-feature routers.
4. **Do not invent new modules.** `CRM | INVOICING | CHART | GENERAL` is fixed. Do not add a new category without explicit approval.
5. **Do not query operational tables for RAG.** Embeddings come from `warehouse.*` only.
6. **Do not prefix agent responses with `[CRM]` / `[INVOICING]` / etc.** The supervisor adds tags.
7. **Do not use any currency other than TND.** No DZD, EUR, USD.
8. **Do not skip `AuditLog`** on mutating operations. Import and call `log_action()` from `backend/utils/audit.py`.
9. **Do not open a DB session without closing it.** Always `get_session()` + `try/finally db.close()`. Never call `SessionLocal()` directly outside `database.py`.
10. **Do not "tweak" prompts by appending ad-hoc rules.** If a rule is needed, edit the existing `SYSTEM_PROMPT` cleanly — don't stack contradictory bullets.
11. **Do not fabricate data from conversation context.** Always call a tool to read DB state.
12. **Do not create new markdown docs, planning files, or summaries** unless explicitly asked. Edit existing files.
13. **Do not add backward-compat shims, `_old`/`_legacy` re-exports, or `# removed` comment markers.** Delete cleanly.
14. **Do not add defensive validation for impossible states.** Validate at boundaries (user input, external APIs) only.
15. **Do not introduce new LLM providers or embedding models.** Ollama `qwen2.5:7b` + `nomic-embed-text` are fixed.
16. **Do not write comments that restate the code.** Only comment non-obvious *why*.
17. **Do not construct `ChatOllama` directly in agent files.** Always use `get_llm()` from `backend/agents/llm.py`.
18. **Do not add rules to a specialist's `SYSTEM_PROMPT` if they belong in `prompt_parts.py`.** A rule shared by two or more specialists goes in `prompt_parts.py`; domain-only rules stay in the specialist.
19. **Do not leave `[DEBUG]`-tagged `print()` statements in production paths.** Use the structured logger from `backend/error_handler.py` if logging is needed.

---

## 3. Workflow — Test Before Committing

Required checks before declaring a task complete or committing:

### 3.1 Static
- Imports resolve: `python -c "import backend.main"` from repo root.
- No unused new files, no stray `print()` debug statements.

### 3.2 Runtime smoke
1. Start stack: `docker-compose up --build` (or `uvicorn backend.main:app --reload --port 8000`).
2. Health check: `GET http://localhost:8000/health` returns OK.
3. If touching a specialist or tool: exercise at least one read + one write (preview + confirm) through `POST /chat`.
4. If touching RAG: run `python -m backend.rag.setup_rag` and verify the test query returns non-empty results.
5. If touching ETL: run `python -m backend.etl.run_etl` against seed data and confirm warehouse tables populate.
6. If touching frontend: open `frontend/index.html` in a browser and run the changed flow end-to-end.

### 3.3 Explicit honesty
- If a check cannot be run in the current environment, say so explicitly. Do **not** claim success based on code inspection alone.
- Type-check / compile passing ≠ feature works. UI/agent correctness must be observed.

### 3.4 Commit discipline
- Only commit when the user asks.
- One logical change per commit. No drive-by refactors bundled with fixes.
- Never use `--no-verify`, `--amend` on published commits, or force-push without explicit instruction.

---

## Quick Reference

| Task | Command |
|---|---|
| Run stack | `docker-compose up --build` |
| Local API | `uvicorn backend.main:app --reload --port 8000` |
| Seed DB | `python -m backend.seed.seed_jbm` |
| ETL | `python -m backend.etl.run_etl` |
| RAG setup | `python -m backend.rag.setup_rag` |
| Dashboards | `streamlit run dashboards/main.py` |
| Airflow | `start_airflow.bat` → http://localhost:8080 |

Default logins after seed: `admin/admin123`, `manager1/pass123`, `agent1/pass123`.
