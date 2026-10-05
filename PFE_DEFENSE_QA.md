# AXIS ERP AI Agent — PFE Defense Q&A Cheat Sheet

> All values extracted directly from source code. Exact file references are included for each claim.

---

## 1. What is AXIS and what problem does it solve?

**Question:** What is AXIS, and what business problem motivated you to build it?

**Key points to hit:**
- Name stands for AI-powered operational management platform
- Target user: IT consulting company (JBM Consulting) with a CRM + billing workflow
- Problem: Business data lives in tables; non-technical staff can't query it
- Solution: Natural language chat interface that routes to specialist agents
- Replaces dashboards and manual SQL with conversational access
- Currency is TND (Tunisian Dinar) throughout — domain-specific, not generic

**60-second answer:**
AXIS is a natural-language ERP assistant for an IT consulting company. The core problem is that operational data — deals, contacts, invoices, activities — lives in a relational database that most employees can't query directly. Every insight requires a developer or a pre-built dashboard, which doesn't scale. AXIS exposes this data through a chat interface at `POST /chat`. The user types a question in French or English; the supervisor routes it to the right specialist agent — CRM, Invoicing, or Chart — which calls the relevant database tools and returns a structured answer. The system is fully local: no cloud LLM calls, all processing happens inside Docker on the company's own hardware.

---

## 2. Why Qwen2.5:7b — why local, why this model?

**Question:** You chose Qwen2.5:7b running locally via Ollama. Why that model, and why not a cloud API?

**Key points to hit:**
- Defined in `backend/agents/llm.py` as `ERP_MODEL = "qwen2.5:7b"`
- All agents import via `from backend.agents.llm import get_llm()` — single definition point
- Local = data privacy: invoices, contacts, deals never leave the company network
- 7B parameter size: fits in ~5–6 GB VRAM, runs on a single mid-range GPU or CPU-offloaded
- Qwen2.5 family has strong instruction-following and tool-calling relative to its size class
- Temperature = 0 for deterministic tool calls (no randomness in routing or writes)
- Separate embedding model: `nomic-embed-text` (768-dim) for RAG — also local via Ollama
- Same model (`qwen2.5:7b`) is reused as the evaluation judge in `backend/evaluation/evaluator.py:154`

**60-second answer:**
We chose Qwen2.5:7b for three reasons. First, data sovereignty: ERP data — salaries, client invoices, deal values — is confidential. Running locally via Ollama means zero data leaves the company network. Second, resource fit: at 7 billion parameters the model needs roughly 5–6 GB of memory, which runs on a single GPU without expensive infrastructure. Third, capability: the Qwen2.5 family has strong tool-calling fidelity at this size compared to alternatives we evaluated. We set temperature to 0 to eliminate randomness in agent decisions. The same model serves as the LLM router, all three specialist agents, and the evaluation judge. For embeddings we use `nomic-embed-text`, a dedicated 768-dimensional embedding model, also local.

--- 

## 3. The 4 Reliability Mechanisms

**Question:** LLMs are non-deterministic and sometimes misbehave. What specific reliability mechanisms did you implement?

**Key points to hit (each is a distinct mechanism):**

### Mechanism 1 — Deterministic Keyword Bypass (`supervisor.py:73–99`)
- Before any LLM call, `fast_route()` scans the message for domain keywords
- `KEYWORD_RULES["INVOICING"]` and `KEYWORD_RULES["CRM"]` are hardcoded lists
- Chart filter regex (`\btop\s+\d+\b` and `above/below X%`) fires before keyword check
- If a keyword matches → route directly, **no LLM call made**
- LLM router is Tier 2 and only fires when Tier 1 returns `None`

### Mechanism 2 — `safe_agent_run` (`tool_interceptor.py:343–524`)
- Wraps every specialist's `agent.invoke()` call
- If the agent's output is empty, it inspects `intermediate_steps` for tool outputs
- If output is a WARNING preview string, passes it through and captures a pending action
- Handles hallucinated confirmation prompts with a forced retry directive
- Acts as a catch-all that prevents silent failures from reaching the user

### Mechanism 3 — Raw JSON Intercept (`tool_interceptor.py:444–524`)
- Qwen2.5:7b occasionally emits a JSON tool-call description instead of executing the tool
- `_extract_tool_call()` runs 3 extraction strategies in order:
  1. Parse entire cleaned string as JSON
  2. Extract first balanced JSON object (brace-counting walker)
  3. Greedy regex fallback `\{[^{}]*\}`
- `_normalize_python_literals()` converts `False/True/None` → `false/true/null`
- If a tool call is found, the interceptor executes it manually via `tool.invoke(params)`

### Mechanism 4 — Schema Reduction for List Queries (`tool_interceptor.py:173–182`)
- Large lists (up to `DEFAULT_LIST_LIMIT = 50` rows from `crm_tools.py:17`) passed raw to the LLM waste context
- `_FORMATTERS` dict maps tool names to deterministic Markdown table formatters:
  `list_contacts`, `list_deals`, `list_invoices`, `list_companies`, `get_invoice`,
  `get_revenue_summary`, `list_saved_charts`, `get_overdue_invoices`
- When intermediate steps contain a formatter-tool output, the interceptor returns it directly, bypassing the LLM synthesis step entirely

**60-second answer:**
We implemented four layers. First, deterministic keyword routing: before touching the LLM, the supervisor scans for domain keywords. If "invoice" appears, it goes to Invoicing with zero AI cost. Second, `safe_agent_run`: every specialist is wrapped in a function that catches empty outputs, inspects intermediate steps, handles hallucinated confirmation prompts with a forced retry, and ensures no silent failure reaches the user. Third, raw JSON interception: Qwen sometimes outputs a JSON description of a tool call instead of executing it. We detect this with three parse strategies — full JSON, brace-counting walker, greedy regex — and execute the tool manually. Fourth, schema reduction: for list queries we bypass the LLM entirely and use deterministic Markdown formatters, which eliminates hallucination on structured table data.

---

## 4. The Confirmation Flow — Two Layers

**Question:** How does the two-phase write confirmation work? What are the two layers and what happens on cancel?

**Key points to hit:**
- **Layer 1 — Tool level** (`backend/tools/*.py`): every write tool accepts `confirmed: bool = False`
  - `confirmed=False` → returns a `"WARNING: about to CREATE/UPDATE/DELETE..."` preview string
  - `confirmed=True` → executes the mutation + writes to `AuditLog` via `log_action()`
  - Pattern enforced by CLAUDE.md anti-pattern rule #2
- **Layer 2 — Supervisor level** (`supervisor.py:424–453`): detects the user's follow-up reply
  - `check_if_confirmation()` fires before routing — checks last assistant message for `_WRITE_PREVIEW_PATTERNS`
  - Positive keywords: `"yes", "yep", "yeah", "yup", "confirm", "confirmed", "oui", "ok", "okay", "vas-y", "d'accord", "sure"`
  - Negative keywords: `"no", "non", "nope", "nah", "cancel", "annuler", "abort"`
  - On positive → message is replaced with: *"The user has confirmed the previous action. Re-execute it now using confirmed=True with the exact same parameters shown in the WARNING."*
  - On negative → returns `"[MODULE]\nOperation cancelled."` immediately, no tool call
- Pending action stored in `session.pending_action` (JSON column), TTL = 5 minutes
- Word-boundary regex prevents "no" matching "notion" or "ok" matching "look"
- Guard: if negative keyword also fast-routes to a domain (e.g. "cancel invoice INV-001"), it's treated as a fresh domain command, not a cancellation

**60-second answer:**
The confirmation system has two layers. At the tool layer, every write tool accepts a `confirmed` boolean. When called with `confirmed=False` it returns a WARNING preview — "about to CREATE contact John Doe at Acme Corp" — without touching the database. The user reads this and replies. At the supervisor layer, before routing the follow-up message, we check whether the last assistant message contained a WARNING pattern. If yes, we classify the reply: positive keywords like "yes", "ok", "confirm" trigger a re-invocation with `confirmed=True`; negative keywords like "no", "cancel", "annuler" immediately return "Operation cancelled" without calling any tool. To prevent false matches, we use word-boundary regex so "no" doesn't match "notion". We also guard against domain verbs: "cancel invoice INV-001" contains "cancel" but fast-routes to Invoicing, so it's treated as a fresh command, not a meta-cancellation.

---

## 5. RAG — Two Collections, What's Embedded, Chunking, Why Not Direct DB

**Question:** Explain the RAG layer — what is embedded, how is it chunked, and why use a vector store instead of just querying the database directly?

**Key points to hit:**
- Two ChromaDB collections, both with `{"hnsw:space": "cosine"}` similarity:
  - `jbm_crm` — activities, deals, companies (from `warehouse.fact_activities`, `warehouse.fact_deals`, `warehouse.dim_client`)
  - `jbm_invoicing` — invoices (from `warehouse.fact_revenue`)
- Embedding model: `nomic-embed-text` via Ollama, 768 dimensions
- Chunking: `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50, separators=["\n\n", "\n", ". ", " ", ""])`
- Batch size: 25 embeddings per Ollama call (`EMBED_BATCH = 25`)
- Source is warehouse-only, never operational tables (CLAUDE.md anti-pattern #5)
- Activity filter: description length > 50 chars, excludes placeholder text
- Retriever returns top-5 docs per query (`top_k=5`); supports company-specific filter
- `ERPRetriever` in `backend/rag/retriever.py` — specialists prepend context before agent invocation
- Why not direct DB: semantic search finds qualitative context ("client meeting went poorly", "renewal discussion") that SQL can't express; RAG adds narrative context to numerical DB results

**60-second answer:**
The RAG layer uses two ChromaDB collections: `jbm_crm` stores embedded activities, deals, and companies; `jbm_invoicing` stores embedded invoices. Both use cosine similarity via the HNSW index. The embedding model is `nomic-embed-text` running locally on Ollama, producing 768-dimensional vectors. Text is split with `RecursiveCharacterTextSplitter` at chunk size 500 with 50-token overlap, using newlines and periods as preferred split points to preserve semantic units. We embed only from warehouse tables — never operational tables — to keep RAG isolated from live write operations. Why RAG instead of direct DB? SQL is excellent for structured queries like "sum of invoices," but it can't answer "what was the sentiment around BNA Bank's last renewal discussion?" RAG retrieves qualitative context from activity descriptions and deal notes, which supplements the agent's database lookups with narrative understanding. The retriever returns the top-5 most similar documents, optionally filtered by company name.

---

## 6. Operational DB vs Data Warehouse — Why Both, Why Data Analyst Uses Warehouse

**Question:** You have both an operational PostgreSQL schema and a `warehouse.*` schema. Why maintain both?

**Key points to hit:**
- Operational tables (`companies`, `contacts`, `deals`, `invoices`, etc.) are the write-path — CRUD operations by CRM and Invoice agents use these via SQLAlchemy ORM
- Warehouse tables (`warehouse.fact_deals`, `warehouse.fact_revenue`, `warehouse.fact_activities`, `warehouse.dim_client`, `warehouse.dim_date`) are read-only analytics-optimised views of the same data
- ETL separates concerns: writes are fast (small normalized tables), analytics are fast (pre-computed joins, denormalized columns like `value_tnd`, `days_to_close`, `payment_delay_days`, `is_overdue`)
- Data Analyst (Chart agent) queries `warehouse.*` exclusively — aggregations over 8,000+ deals or 200,000+ activities need pre-computed fact tables, not ad-hoc JOINs across 10 normalized tables
- ML models train on `warehouse.*` — clean, denormalized, with derived features already computed
- RAG embeddings come from `warehouse.*` — consistent with the analytics layer
- If Data Analyst queried operational tables directly, every chart would require multi-table JOINs with runtime joins; the warehouse already has `company_name` denormalized into every fact row

**60-second answer:**
We maintain two schemas because they serve fundamentally different purposes. The operational schema handles writes — when you create a deal or update an invoice, the CRM agent inserts into `deals`, `companies`, `invoices`. These tables are normalized for data integrity. The warehouse schema is the analytics layer: the ETL pipeline pre-computes joins, derived columns like `days_to_close`, `payment_delay_days`, and `is_overdue`, and denormalizes company names into every fact row. The Data Analyst agent only queries `warehouse.*` because chart queries aggregate thousands of rows — "revenue by quarter" across 2,000 invoices — and doing that via JOINs on normalized operational tables would be both slow and fragile. The ML models also train exclusively on the warehouse for the same reason: features like `churn_signal_ratio`, `overdue_ratio`, and `activity_frequency` are computed during ETL. The separation means writes are always fast and analytics are always clean.

---

## 7. ML Models — Why Random Forest, Why Logistic Regression, Calibration

**Question:** Explain your ML architecture for churn and deal prediction. Why those algorithms? What is calibration and why did you apply it?

**Key points to hit:**

**Training pipeline (both models — `churn_model.py` and `deal_model.py`):**
- Three candidates trained: `LogisticRegression(max_iter=1000, class_weight="balanced")`, `RandomForestClassifier(n_estimators=200, class_weight="balanced")`, optional `XGBClassifier(n_estimators=200, scale_pos_weight=...)`
- 80/20 stratified train/test split (`test_size=0.2, stratify=y, random_state=42`)
- `StandardScaler` applied before training
- Best model selected by F1 score (`results_df["f1"].idxmax()`)
- Churn: best model selected dynamically; Deal: hardcoded `best_name = "RandomForest"`

**Why Random Forest:**
- Handles mixed numerical features (days, counts, ratios) without feature scaling assumption violations
- Naturally captures non-linear interactions (e.g., high churn signals × low activity)
- `feature_importances_` gives explainability for the top-5 factor display
- `class_weight="balanced"` handles imbalanced churn label (~20–35% churn rate)

**Why Logistic Regression (in the ensemble):**
- Baseline comparison: if LR matches RF performance, the problem is linearly separable
- `coef_[0]` also provides feature importance for explainability
- Faster to train and more interpretable for academic review

**Calibration:**
- Both models wrapped with `CalibratedClassifierCV(best_model, cv=5, method="sigmoid")` — Platt scaling
- Platt scaling fits a sigmoid curve on cross-validated probability outputs, mapping raw model scores to well-calibrated probabilities
- Post-hoc linear temperature scaling applied at inference:
  - Churn: `prob = 0.5 + (prob - 0.5) * 0.75` (`predictor.py:73`) — dampens extreme predictions
  - Deal: `prob = 0.5 + (prob - 0.5) * 0.55` (`deal_predictor.py:101`) — more dampening because deal outcomes are noisier
- Risk thresholds after calibration:
  - Churn: High > 0.7 / Medium 0.4–0.7 / Low < 0.4
  - Deal: Likely Win > 0.65 / Uncertain 0.35–0.65 / Likely Loss < 0.35

**60-second answer:**
We train three models — Logistic Regression, Random Forest, and XGBoost if available — and select the best by F1 score, which balances precision and recall on the imbalanced churn label. Random Forest wins most of the time because it handles the mixed numerical features — days, ratios, counts — without distributional assumptions, and captures non-linear interactions. We use `class_weight="balanced"` to compensate for the churn minority class. After training, the best model is wrapped in `CalibratedClassifierCV` with Platt scaling and 5-fold cross-validation. Platt scaling maps the raw model score through a sigmoid to produce well-calibrated probabilities. We then apply a second linear scaling at inference: churn probabilities are compressed to `0.5 + (p - 0.5) * 0.75` and deal probabilities to `0.5 + (p - 0.5) * 0.55`. This dampens extreme predictions because our training dataset is relatively small — overconfident probabilities would mislead the business recommendations layer.

---

## 8. Routing — Labels, Two-Layer Architecture, Failure Handling

**Question:** How does the routing system work? Walk me through all layers and what happens when each one fails.

**Key points to hit:**
- **Valid modules:** `CRM`, `INVOICING`, `CHART`, `GENERAL`, `DYNAMIC` (`supervisor.py:43`)
- **LLM router classifies to 4 labels:** `CRM`, `INVOICING`, `CHART`, `GENERAL` (router prompt excludes DYNAMIC)
- **Layer 0 — Confirmation check** (`check_if_confirmation()`): fires before any routing; if last assistant message contained a WARNING pattern and user replied with a confirmation keyword, route back to same specialist immediately
- **Tier 1a — Regex pre-check:** `_CHART_FILTER_RE` catches "top 5", "above 30%" before keyword scan — prevents chart requests being stolen by CRM keywords
- **Tier 1b — Chart keyword check:** 13 chart keyword phrases checked before CRM/INVOICING
- **Tier 1c — INVOICING keywords:** 15 keywords checked before CRM (to prevent "invoice for client X" routing to CRM)
- **Tier 1d — CRM keywords:** 30+ keywords including ML-specific ones ("churn", "win probability", "deal prediction")
- **Tier 1e — Dynamic agent registry:** `find_agent_for_message()` checked last among fast routes
- **Tier 2 — LLM router:** `qwen2.5:7b` called only when Tier 1 returns `None`; returns one of 4 labels
- **Failure handling:**
  - If LLM returns unrecognized module → `logger.warning` + default to `GENERAL`
  - If LLM call throws exception → `logger.error` + default to `GENERAL`
  - GENERAL is handled by a separate `handle_general()` LLM chain
- **Disambiguation sticky routing:** if last CRM response contained "did you mean" / "which one" / "not found" patterns, short follow-up replies route back to CRM without LLM call

**60-second answer:**
Routing has two tiers. Before either fires, a Layer 0 checks whether this is a confirmation reply to a pending write operation. Tier 1 is deterministic keyword matching: we first check for chart filter patterns like "top 5" or "above 30%" via regex, then chart keywords, then INVOICING keywords, then CRM keywords — in that order so more specific patterns beat generic ones. CRM has over 30 keywords including ML-specific ones like "churn", "win probability", and "predict deal." Only when Tier 1 returns nothing do we invoke the LLM. The router prompt instructs Qwen to return exactly one of four labels: CRM, INVOICING, CHART, or GENERAL. If the LLM returns an unrecognized string or throws an exception, we log the error and default to GENERAL, ensuring the user always gets a response. DYNAMIC is a fifth valid module for meta-agent-generated specialists, checked between tiers.

---

## 9. Evaluation Module — Metrics, Score Calculation, What 79% Means

**Question:** How did you evaluate the system? Explain all the test cases, how scoring works, and what a 79% average score means in practice.

**Key points to hit (`backend/evaluation/evaluator.py`):**

**12 test cases across 3 agents:**
- **CRM (5 tests):** CRM-01 total deals, CRM-02 win rate %, CRM-03 total companies, CRM-04 active pipeline value TND, CRM-05 deals in Negotiation stage
- **Finance (5 tests):** FIN-01 total collected revenue, FIN-02 collection rate %, FIN-03 overdue invoice count, FIN-04 total pending amount, FIN-05 total invoice count
- **Data Analyst (2 tests):** DA-01 bar chart of deal count by stage, DA-02 pie chart of invoice status distribution

**Ground truth mechanism:**
- Each test case has a `ground_truth_sql` field — a SQL query that runs against `warehouse.*` to get the true answer
- This makes evaluation database-grounded, not human-annotated

**Scoring (LLM-as-Judge):**
- Judge model: `JUDGE_MODEL = "qwen2.5:7b"` (`evaluator.py:154`)
- Judge scores 0–100 on 3 dimensions: factual correctness, completeness, relevance
- Data Analyst special rule: score ≥ 80 if chart was created successfully
- Verdicts: PASS ≥ 70 / PARTIAL 40–69 / FAIL < 40
- `overall_score = sum(scores) / total_tests` — simple mean

**What 79% average means:**
- 79 out of 100 average judge score across all 12 tests
- Falls in the PASS band (≥ 70)
- Means: the system answers correctly and completely on the majority of factual queries
- Primary limitation: Data Analyst tests drag the average if chart rendering or warehouse data is stale; CRM/Finance tests typically score higher because they return direct numerical values

**60-second answer:**
We built a 12-test evaluation suite with three agent categories: 5 CRM tests, 5 Finance tests, and 2 Data Analyst tests. Each test has a ground-truth SQL query that runs against the warehouse to get the exact correct answer. The system is then asked the same question via the `/chat` endpoint, and a Qwen2.5:7b judge scores the response from 0 to 100 on factual correctness, completeness, and relevance. A score of 70 or above is a PASS. The overall score is the simple mean across all 12 tests. A 79% average means we're solidly in the PASS band: most factual queries about deals, invoices, and pipeline return correct numbers, and both chart generation tests succeeded. The main limitations are that the judge is the same model as the agent, which creates potential bias, and chart tests are sensitive to whether the warehouse data is fresh.

---

## 10. Limitations and Future Improvements

**Question:** What are the limitations of your current system, and what would you improve with more time?

**Key points to hit:**

**Technical limitations:**
- **LLM quality ceiling:** Qwen2.5:7b sometimes fails on complex multi-step reasoning; tool-calling reliability requires the 4 reliability mechanisms as compensators
- **Latency:** End-to-end response can take 8–20 seconds on CPU; Tier 1 keyword routing helps but Tier 2 LLM calls are slow
- **Self-referential evaluation:** judge model = agent model → potential circular scoring bias
- **RAG staleness:** ChromaDB is populated by a one-time setup script; it doesn't auto-refresh when operational data changes (incremental `--update` mode exists but isn't automated)
- **No streaming:** responses are returned as a single JSON payload; no SSE/WebSocket streaming
- **Session memory cap:** only the last 20 messages are stored per session; long conversations lose early context

**ML limitations:**
- **Small training dataset:** churn and deal models trained on company's own historical data — limited sample size; churn label is auto-generated from heuristics (inactivity threshold, churn signal ratio) rather than actual observed churn events
- **Static feature set:** model features are computed at training time; new activity types not in `ACT_COL_MAP` are ignored

**Future improvements:**
- **Upgrade to a larger model** (Qwen2.5:14b or 32b) for improved tool-calling reliability and less need for the interceptor layer
- **Streaming responses** via FastAPI `StreamingResponse` + SSE
- **Meta-agent** (already scaffolded in `backend/agents/meta_agent.py`, disabled in current scope) — allows dynamically generating new specialist agents from natural language descriptions
- **Automated RAG refresh** triggered by the ETL Airflow DAG post-load
- **External judge model** for evaluation to eliminate circular bias
- **HR and Project specialist agents** — the warehouse already has `fact_hr_events` and `fact_project_performance` tables

**60-second answer:**
The main technical limitation is the LLM's tool-calling reliability — Qwen2.5:7b requires four compensating mechanisms just to be production-stable. Response latency on CPU can reach 15–20 seconds, which is acceptable for an internal tool but not for a consumer product. Our evaluation has a circular bias issue: we use the same model as both agent and judge. On the ML side, the training data is limited to one company's history, and the churn labels are heuristically generated rather than from observed churn events. For future work, the highest-impact improvements would be: upgrading to a 14B or 32B model, enabling the meta-agent feature that's already scaffolded in the codebase, adding streaming responses, and automating RAG refresh after each ETL run. The warehouse also already contains HR and Project tables ready for new specialist agents.

---

## 11. Docker — 5 Containers, Startup Order, Why Containerization

**Question:** Explain your Docker architecture. What are the containers, what order do they start, and why containerize this system?

**Key points to hit (from `docker-compose.yml`):**

**5 containers:**
| Service | Image | Port | Role |
|---|---|---|---|
| `axis-db` | `postgres:16` | 5432 (internal) | Operational + warehouse database |
| `axis-chromadb` | `chromadb/chroma:0.4.24` | 8001 (internal) | Vector store for RAG |
| `axis-ollama` | `ollama/ollama:latest` | 11434 (internal) | LLM + embedding runtime |
| `axis-backend` | Custom Dockerfile | 8000 (internal) | FastAPI application |
| `axis-frontend` | `frontend/Dockerfile` | 80:80 (external) | Nginx static server |

**Startup order (dependency graph):**
1. `axis-db` starts first — healthcheck: `pg_isready` (interval 10s, 5 retries)
2. `axis-chromadb` + `axis-ollama` start in parallel once `axis-db` is healthy
3. `axis-backend` starts once `axis-db` healthy + `axis-chromadb` and `axis-ollama` started
4. `axis-frontend` starts once `axis-backend` is healthy (healthcheck: `GET /health`)

**Why containerization:**
- Reproducibility: entire stack launched with `docker-compose up --build`
- Environment isolation: Ollama with GPU pass-through stays in its own container
- Port isolation: nothing is exposed except port 80 (frontend) — all internal communication uses Docker network service names (`axis-db`, `axis-ollama`, etc.)
- Persistent volumes: `postgres-data`, `chroma-data`, `ollama-models`, `backend-logs` survive container restarts
- `restart: unless-stopped` ensures the system recovers from crashes automatically

**60-second answer:**
The system runs as 5 Docker containers. The database starts first and is health-checked with `pg_isready`. Once it's healthy, ChromaDB and Ollama start in parallel — they're independent, so we don't make one wait for the other. The FastAPI backend starts once the database is healthy and ChromaDB and Ollama have started. The frontend Nginx server starts last, once the backend passes its own health check. The only externally exposed port is 80; everything else communicates via Docker's internal network using service names. We chose full containerization because the dependency chain — PostgreSQL, ChromaDB, Ollama, Python — is complex to install consistently. With Docker, the entire stack starts with a single command and survives reboots via `restart: unless-stopped`.

---

## 12. ETL Pipeline — 14 Steps, What It Does, Why Manual Trigger

**Question:** Explain the ETL pipeline. What are the 14 steps, what does it transform, and why is it manually triggered?

**Key points to hit (from `airflow/dags/etl_jbm_pipeline.py`):**

**DAG ID:** `jbm_etl_pipeline` — Apache Airflow, `schedule_interval="@daily"` (but manually triggered in practice)

**14 steps (4 entities × 3 phases + dim_date + validate):**
| # | Task ID | What it does |
|---|---|---|
| 1 | `extract_clients` | Reads `raw_clients.xlsx` → `staging/raw_clients.csv` |
| 2 | `transform_clients` | Deduplicates (fuzzy match ≥ 85%), normalises city/country/industry/phone, `status` → active/inactive/prospect/churned |
| 3 | `load_clients` | Truncate + COPY into `warehouse.dim_client` |
| 4 | `extract_deals` | Reads `raw_deals.xlsx` → `staging/raw_deals.csv` |
| 5 | `transform_deals` | Keeps latest event per deal_id, parses `value_tnd` (handles "50k", "1.2M"), normalises stage (`négociation` → `Negotiation`), computes `days_to_close`, `deal_size_category`, `quarter`; EUR×3.35 / USD×3.10 → TND |
| 6 | `load_deals` | Truncate + COPY into `warehouse.fact_deals` |
| 7 | `extract_activities` | Reads `raw_activities.xlsx` → `staging/raw_activities.csv` |
| 8 | `transform_activities` | Chunks at 50k rows, normalises `activity_type`, parses `duration_min`, keyword-scores `churn_signal` / `positive_signal` from description text |
| 9 | `load_activities` | Truncate + COPY into `warehouse.fact_activities` in 10k-row chunks |
| 10 | `extract_invoices` | Reads `raw_invoices.xlsx` → `staging/raw_invoices.csv` |
| 11 | `transform_invoices` | Standardises invoice number → `JBM-YYYY-NNNN`, computes `tax_amount = subtotal × 0.19`, derives `payment_delay_days`, `is_overdue`, `days_outstanding` |
| 12 | `load_invoices` | Truncate + COPY into `warehouse.fact_revenue` |
| 13 | `populate_dim_date` | Fills `warehouse.dim_date` for 2023-01-01 → 2026-12-31 with Tunisian public holidays |
| 14 | `validate_warehouse` | Checks row counts (fact_deals ≥ 3,000; fact_activities ≥ 50,000; fact_revenue ≥ 500; dim_client ≥ 500), verifies no null PKs, checks revenue trend and win rate in 10–90% range |

**Parallelism:** steps 1–12 run as 4 parallel chains (clients, deals, activities, invoices); dim_date waits for all 4 loads to complete; validate runs last.

**Why manually triggered (not automated):**
- Source data is Excel files delivered by the company's existing processes — there is no automated data feed
- Running ETL on stale or partial Excel files would corrupt the warehouse
- `retries: 2, retry_delay: 5 minutes` provides resilience for transient DB failures
- The `etl_pipeline.py` also has a Python standalone runner (`python -m backend.etl.run_etl`) for development

**60-second answer:**
The ETL pipeline is an Airflow DAG with 14 Python tasks. It processes four entities — clients, deals, activities, invoices — each through extract, transform, load phases, running as four parallel chains. After all four load tasks complete, it populates the date dimension and runs a validation check. The transform phase does heavy lifting: it fuzzy-deduplicates company names at an 85% similarity threshold, converts deal values from shorthand like "50k" or "1.2M" to numeric TND, normalises French stage names to English, computes `days_to_close`, and keyword-scores each activity description for churn and positive signals. The invoice transform applies 19% TVA and derives overdue status. The final validate step asserts minimum row counts and rejects runs where the win rate is outside the 10–90% range, acting as a data quality gate. We trigger it manually because the source data is Excel files — there's no automated upstream feed, so automatic scheduling on stale files would corrupt the warehouse.

---

## Bonus: Additional Topics Worth Knowing

### Audit Logging
- Every write tool must call `log_action(db, action, entity, entity_id, payload, result)` from `backend/utils/audit.py`
- Enforced by CLAUDE.md anti-pattern #8: "Do not skip AuditLog on mutating operations"
- All mutations are traceable: who did what, to which record, with which parameters

### Session Management
- `ChatSession` model stores last 20 messages (`main.py:271`)
- `session.pending_action` (JSON column) holds tool parameters from preview turns, TTL = 5 minutes
- `session_id` is client-provided; new UUID created if omitted

### Data Quality in the Pipeline
- Company name fuzzy deduplication: `rapidfuzz.fuzz.token_sort_ratio` ≥ 85% merges variants
- `churn_signal` detected by 15 French keywords (e.g., "insatisfait", "concurrent", "problème")
- `positive_signal` detected by 16 French keywords (e.g., "satisfait", "renouvellement", "fidèle")
- Invoice numbers standardised to `JBM-YYYY-NNNN` format

### LLM Factory Pattern
- `backend/agents/llm.py` is the single definition point for `ERP_MODEL = "qwen2.5:7b"`
- All agents import via `from backend.agents.llm import get_llm()`
- Temperature: 0 (deterministic)
- CLAUDE.md anti-pattern #17: never construct `ChatOllama` directly in agent files

### Shared Prompt Scaffold
- `backend/agents/prompt_parts.py` holds constants shared across ≥ 2 specialists
- TND formatting rule, language handling, tool enforcement, confirmation system
- Domain-specific rules stay in each specialist file
- Prevents contradictory prompt stacking (CLAUDE.md anti-pattern #10)

---

*Generated from source code — values are exact. Cross-reference with files for live defense questions.*
