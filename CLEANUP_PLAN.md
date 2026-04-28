# CLEANUP_PLAN.md

Roadmap for bringing the codebase in line with `CLAUDE.md`. Fixes architecture first, then the bugs that fall out of it. Each step is independent and shippable on its own — no step depends on a later one.

---

## Findings (evidence)

| # | Problem | Evidence |
|---|---|---|
| A | `get_db()` defined 3× | `backend/models/database.py:16`, `backend/tools/crm_tools.py:17`, `backend/tools/invoice_tools.py:15` |
| B | `SessionLocal()` called directly in 10+ places instead of via `get_db()` | `main.py:44,89,203,216`, `agents/crm_specialist.py:126`, `agents/invoice_specialist.py:115`, `etl/etl_pipeline.py:525`, seed scripts, etc. Many lack `try/finally` close. |
| C | `ChatOllama(model="qwen2.5:7b", temperature=0)` constructed 5× | `supervisor.py:272,304`, `crm_specialist.py:156`, `invoice_specialist.py:130`, `chart_agent.py:79`. No single source of truth for model config. |
| D | Three seed scripts coexist | `backend/seed/seed_all.py`, `seed_data.py`, `seed_jbm.py`. CLAUDE.md declares `seed_jbm` canonical — the others are dead weight and drift risk. |
| E | Three near-duplicate `SYSTEM_PROMPT` blocks with overlapping rules | `crm_specialist.py`, `invoice_specialist.py`, `chart_agent.py`. Shared rules (TND formatting, language mirroring, no `[TAG]` prefix, confirmation keywords) are copy-pasted and drift independently. |
| F | Two routing bodies inside one file | `supervisor.py:272` and `:304` each instantiate their own LLM — suggests a duplicated router path that should be one function. |
| G | `AuditLog` / `log_action` only lives in `crm_tools.py` | `backend/tools/crm_tools.py:21`. Invoice write tools cannot share it cleanly — likely either duplicated there or skipped entirely (violates CLAUDE.md §2.8). |

---

## Step 1 — Collapse the seed scripts (lowest risk, highest clarity win)

**Goal:** single seed entry point, matching CLAUDE.md.

- Confirm `seed_jbm.py` is the only one referenced by docs, Docker, and scripts.
- Delete `seed_all.py` and `seed_data.py` (no re-export shims — see CLAUDE.md §2.13).
- Grep for any stale imports of the deleted modules and clean them.

**Why first:** zero architectural risk, removes the easiest source of future drift, and shrinks the surface for later steps.

**Done when:** `backend/seed/` contains only `seed_jbm.py` + `__init__.py`, and `python -m backend.seed.seed_jbm` still seeds cleanly.

---

## Step 2 — One `get_db()`, one session lifecycle

**Goal:** a single canonical DB accessor, used everywhere.

- Keep `get_db()` in `backend/models/database.py` as the only definition.
- Delete the duplicates in `crm_tools.py` and `invoice_tools.py`; import from `models.database` instead.
- Replace raw `SessionLocal()` calls in `main.py`, specialists, ETL, and seeds with `get_db()`.
- Audit every call site for the `try/finally db.close()` pattern required by CLAUDE.md §1.4 / §2.9. Flag (don't fix yet) any site missing it — that's Step 5.

**Why second:** it's purely a refactor, makes the bug-hunt in Step 5 mechanical, and unblocks shared helpers (Step 4).

**Done when:** `grep -n "def get_db"` returns exactly one hit, and no module outside `database.py` calls `SessionLocal()` directly.

---

## Step 3 — Centralize the LLM factory

**Goal:** one place that knows what model the app uses.

- Add `backend/agents/llm.py` exposing `get_llm(temperature=0)` that returns `ChatOllama(model="qwen2.5:7b", temperature=temperature)`.
- Replace the 5 inline constructions in `supervisor.py`, `crm_specialist.py`, `invoice_specialist.py`, `chart_agent.py` with `get_llm()`.
- While there, collapse the two router blocks in `supervisor.py:272` / `:304` into one function if they are genuinely duplicates (verify first; if not, leave and document why).

**Why third:** enforces CLAUDE.md §2.15 (no new LLM providers sneaking in), and makes future model swaps a one-line change instead of a grep-and-replace.

**Done when:** `grep -n "ChatOllama("` returns one hit, in `llm.py`.

---

## Step 4 — Extract the shared agent prompt scaffold

**Goal:** stop copy-pasting the same rules across three specialist prompts.

- Create `backend/agents/prompt_parts.py` (or a dict of constants) holding the rules that are genuinely shared: TND formatting, language-mirroring, confirmation keywords, "no `[TAG]` prefix", "always call tools, never fabricate".
- Rewrite each specialist's `SYSTEM_PROMPT` to compose: `COMMON_RULES + domain-specific rules + output format`.
- Move `log_action` / `AuditLog` helper out of `crm_tools.py` into a shared `backend/tools/_audit.py` so invoice write tools can use the same audit path (CLAUDE.md §2.8).

**Why fourth:** this is the riskiest refactor — it touches agent behavior — so it goes after the cheaper structural wins. With Steps 1–3 done, the diff stays readable and reviewable.

**Done when:** each specialist prompt contains only its domain-specific rules; shared rules live in one file; invoice write tools log to `AuditLog`.

---

## Step 5 — Sweep the bugs the refactor exposed

**Goal:** fix the per-site bugs that Steps 2–4 made visible, now that the architecture is stable.

Expected punch list (verify during the sweep):
- Missing `try/finally db.close()` on `SessionLocal()` call sites flagged in Step 2.
- Invoice write tools not writing to `AuditLog` (Step 4 gave them the helper).
- Any `[CRM]` / `[INVOICING]` prefix leaks from specialists (CLAUDE.md §2.6).
- Currency strings that aren't "TND" (CLAUDE.md §2.7).
- Ad-hoc rule bullets appended to prompts that are already covered by the shared scaffold (CLAUDE.md §2.10).
- Stale `print()` debug statements and unreachable `_old` / `_v2` helpers.

**Why last:** fixing these first would just mean re-fixing them after the refactor. Doing them now, against a clean architecture, means each fix is one line and each regression would be obvious.

**Done when:** every item in the punch list is either fixed or explicitly deferred with a reason in a follow-up issue.

---

## Explicitly out of scope

- Rewriting the two-phase write pattern.
- Changing the routing tiers or adding modules.
- Migrating off Ollama or ChromaDB.
- Touching the frontend or ETL transformation logic.

These are working as designed per CLAUDE.md; leave them alone.
