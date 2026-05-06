# AXIS — Complete Technical Documentation
## Agentic eXecution & Intelligence System
### Exhaustive Engineering Reference for Academic Report

---

> **Scope**: Every engineering decision, bypass, fallback, tool, agent, pipeline step, and ML model in the AXIS codebase. Nothing omitted.  
> **Currency**: TND throughout.  
> **Reference date**: 2026-05-06.

---

## Table of Contents

1. [Complete Project File Map](#1-complete-project-file-map)
2. [Supervisor Agent — Complete Routing Logic](#2-supervisor-agent--complete-routing-logic)
3. [CRM Specialist Agent — Complete Tool Inventory](#3-crm-specialist-agent--complete-tool-inventory)
4. [Invoicing Agent — Complete Tool Inventory](#4-invoicing-agent--complete-tool-inventory)
5. [Analytics / Chart Agent — Complete Tool Inventory](#5-analytics--chart-agent--complete-tool-inventory)
6. [ETL Pipeline — Every Step](#6-etl-pipeline--every-step)
7. [RAG System — Complete Implementation](#7-rag-system--complete-implementation)
8. [Authentication & User Management](#8-authentication--user-management)
9. [Machine Learning Models](#9-machine-learning-models)
10. [Frontend & UI — Complete Feature Map](#10-frontend--ui--complete-feature-map)
11. [Error Handling — Complete Architecture](#11-error-handling--complete-architecture)
12. [Docker & Deployment](#12-docker--deployment)
13. [LLM Selection & All Models Used](#13-llm-selection--all-models-used)
14. [Database Schemas](#14-database-schemas)
15. [Configuration & Constants](#15-configuration--constants)

---

## 1. Complete Project File Map

### 1.1 Directory Tree

```
erp-ai-agent/
├── .env                              # Runtime secrets and env overrides
├── CLAUDE.md                         # Source-of-truth guide for development
├── docker-compose.yml                # Two-service stack: db + api
├── docker-compose.airflow.yml        # Airflow scheduler/worker/webserver
├── rebuild_warehouse.sql             # Manual SQL warehouse rebuild from operational DB
├── cleanup_companies.sql             # Company name deduplication migration
├── cleanup_residuals_preview.sql     # Preview residuals before pass2 cleanup
├── cleanup_residuals_pass2.sql       # Two-pass pg_trgm fuzzy cleanup
├── backup_before_company_cleanup_2026-04-16.sql
│
├── backend/
│   ├── main.py                       # FastAPI app, /chat endpoint, startup
│   ├── auth.py                       # JWT + bcrypt authentication
│   ├── error_handler.py              # ERPErrorType enum, handle_* functions
│   │
│   ├── agents/
│   │   ├── context.py                # Per-request ContextVars (asyncio)
│   │   ├── llm.py                    # LLM factory — get_llm(), ERP_MODEL
│   │   ├── prompt_parts.py           # Shared prompt string constants
│   │   ├── supervisor.py             # Routing orchestrator — run_agent()
│   │   ├── crm_specialist.py         # CRM agent + deterministic bypass map
│   │   ├── invoice_specialist.py     # Invoice agent + time-param extraction
│   │   ├── chart_agent.py            # Chart agent + fabrication detection
│   │   └── tool_interceptor.py       # safe_agent_run(), formatter cascade
│   │
│   ├── tools/
│   │   ├── crm_tools.py              # 23 CRM @tool functions
│   │   ├── invoice_tools.py          # 11 invoice @tool functions
│   │   ├── chart_tools.py            # 3 chart @tool functions
│   │   └── prediction_charts.py      # Batch ML prediction for charts
│   │
│   ├── models/
│   │   ├── database.py               # SQLAlchemy engine, get_session(), get_db()
│   │   ├── crm_models.py             # User, Company, Contact, Deal, Activity, AuditLog, Session
│   │   ├── invoice_models.py         # Invoice, InvoiceItem, Payment
│   │   └── warehouse_models.py       # DimDate, DimClient, DimEmployee, DimService,
│   │                                 # FactRevenue, FactDeals, FactProjectPerformance, FactHrEvents
│   │
│   ├── ml/
│   │   ├── churn_model.py            # Churn training pipeline
│   │   ├── deal_model.py             # Deal win training pipeline
│   │   ├── predictor.py              # Churn inference (predict_company_churn)
│   │   ├── deal_predictor.py         # Deal win inference (predict_deal_outcome)
│   │   ├── churn_model.joblib        # Trained churn model artifact
│   │   ├── scaler.joblib             # Churn StandardScaler artifact
│   │   ├── feature_names.joblib      # Churn feature name list artifact
│   │   ├── deal_model.joblib         # Trained deal win model artifact
│   │   ├── deal_scaler.joblib        # Deal win StandardScaler artifact
│   │   └── deal_feature_names.joblib # Deal win feature name list artifact
│   │
│   ├── rag/
│   │   ├── retriever.py              # ERPRetriever class — ChromaDB queries
│   │   ├── embedding_pipeline.py     # run_full_pipeline(), run_incremental_update()
│   │   └── setup_rag.py              # CLI entry point for RAG initialization
│   │
│   ├── etl/
│   │   ├── run_etl.py                # Standalone ETL runner (no Airflow required)
│   │   └── etl_pipeline.py           # DEPRECATED legacy ORM-based ETL
│   │
│   ├── evaluation/
│   │   ├── __init__.py
│   │   └── evaluator.py              # LLM-as-Judge eval framework, 12 test cases
│   │
│   ├── routes/
│   │   └── axis.py                   # Admin, ETL trigger, charts, KPI, eval routes
│   │
│   ├── utils/
│   │   └── audit.py                  # log_action() — AuditLog writer
│   │
│   ├── migrations/
│   │   ├── drop_invoices_project_id.sql
│   │   └── update_evaluation_schema.sql
│   │
│   └── seed/
│       └── seed_jbm.py               # Deterministic seed: admin + 3 users
│
├── airflow/
│   └── dags/
│       └── etl_jbm_pipeline.py       # PRIMARY ETL DAG (14 tasks, star schema)
│
├── data/
│   ├── generate_raw_data.py          # Synthetic data generator
│   ├── populate_operational.py       # Loads CSVs into operational tables
│   └── staging/                      # Intermediate ETL CSV files
│
├── static/
│   └── axis.html                     # Complete single-file frontend SPA
│
├── chroma_db/                        # Persistent ChromaDB vector store
│   ├── jbm_crm/                      # CRM embeddings collection
│   └── jbm_invoicing/                # Invoicing embeddings collection
│
├── tasks/
│   ├── lessons.md                    # Engineering lessons learned
│   └── known_issues.md               # Known issues tracker
│
└── logging_config.py                 # Structured logging configuration
```

### 1.2 Entry Points

| Command | Entry Point | Purpose |
|---------|------------|---------|
| `uvicorn backend.main:app` | `backend/main.py` | Main API server |
| `python -m backend.etl.run_etl` | `backend/etl/run_etl.py` | Standalone ETL |
| `python -m backend.rag.setup_rag` | `backend/rag/setup_rag.py` | RAG initialization |
| `python -m backend.seed.seed_jbm` | `backend/seed/seed_jbm.py` | DB seeding |
| `python backend/ml/churn_model.py` | `backend/ml/churn_model.py` | Train churn model |
| `python backend/ml/deal_model.py` | `backend/ml/deal_model.py` | Train deal model |

---

## 2. Supervisor Agent — Complete Routing Logic

**File**: `backend/agents/supervisor.py`  
**Purpose**: Receives every user message from `/chat`, applies a four-tier routing cascade, dispatches to the correct specialist, returns the tagged response.

### 2.1 Architecture: Four-Tier Routing Cascade

```
User message
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  TIER 0: Confirmation check                             │
│  Is there a pending_action in session AND message       │
│  matches positive/negative confirmation keywords?       │
│  → YES: skip all routing, re-invoke with confirmed=True │
│           or discard and reply "Cancelled."             │
└─────────────────────────────────────────────────────────┘
    │ (no pending action or no match)
    ▼
┌─────────────────────────────────────────────────────────┐
│  TIER 0b: Context continuation check                    │
│  Does the previous assistant turn contain a             │
│  disambiguation question AND this message is short?     │
│  → YES: inherit module from last assistant tag          │
└─────────────────────────────────────────────────────────┘
    │ (no context match)
    ▼
┌─────────────────────────────────────────────────────────┐
│  TIER 1: Deterministic fast_route()                     │
│  Keyword match: KEYWORD_RULES dict +                    │
│  chart keyword list + chart filter regex                │
│  → Returns module string or None. O(1), no LLM.        │
└─────────────────────────────────────────────────────────┘
    │ (no keyword match → None)
    ▼
┌─────────────────────────────────────────────────────────┐
│  TIER 2: LLM router (Ollama qwen2.5:7b)                 │
│  Router prompt → returns JSON {"module": "CRM|..."}    │
│  Validated against VALID_MODULES set                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
  Specialist agent (CRM / INVOICING / CHART / GENERAL)
```

### 2.2 Confirmation Keyword Sets

```python
_POSITIVE_CONFIRMATION_KEYWORDS = {
    "yes", "oui", "confirm", "confirme", "confirmer", "confirmed",
    "go ahead", "proceed", "do it", "ok", "okay", "sure",
    "yep", "yeah", "absolutely", "correct", "affirmative",
    "validate", "valider", "execute", "exécuter",
}

_NEGATIVE_CONFIRMATION_KEYWORDS = {
    "no", "non", "cancel", "annuler", "abort", "stop",
    "don't", "do not", "nope", "negative", "refuse",
}
```

### 2.3 Write Preview Detection Patterns

```python
_WRITE_PREVIEW_PATTERNS = [
    r"\b(create|add|insert|new)\b",
    r"\b(update|edit|modify|change)\b",
    r"\b(delete|remove|drop)\b",
    r"\b(send|mark|cancel)\b",
]
```

### 2.4 Context Continuation Patterns

```python
_CONTEXT_CONTINUATION_PATTERNS = [
    r"\bdid you mean\b",
    r"\bwhich one\b",
    r"\bplease clarify\b",
    r"\bwhich company\b",
    r"\bwhich deal\b",
    r"\bdo you mean\b",
    r"\bcan you specify\b",
    r"\bplease specify\b",
]
```

### 2.5 Disambiguation Patterns

Used by the context continuation check to detect when the last assistant turn asked a clarifying question. If the last assistant response contains a `_CONTEXT_CONTINUATION_PATTERN` AND carries a module tag (e.g., `[CRM]`), the current short reply inherits that module without LLM routing.

### 2.6 KEYWORD_RULES Dictionary (Tier 1)

```python
KEYWORD_RULES = {
    "CRM": [
        "deal", "deals", "pipeline", "company", "companies", "client", "clients",
        "contact", "contacts", "activity", "activities", "churn", "predict",
        "win rate", "stage", "negotiation", "prospect", "lead", "crm",
        "at risk", "risk", "create company", "create deal", "create contact",
        "delete company", "delete deal", "update company", "update deal",
        "close deal", "won", "lost", "open deal", "sales",
    ],
    "INVOICING": [
        "invoice", "invoices", "bill", "billing", "payment", "payments",
        "revenue", "overdue", "balance", "paid", "pending", "total invoiced",
        "create invoice", "send invoice", "mark paid", "cancel invoice",
        "tva", "tax", "subtotal", "amount due",
    ],
    "CHART": [
        # (handled separately via _CHART_KEYWORDS list)
    ],
    "GENERAL": [
        "help", "hello", "hi", "what can you do", "how do i",
    ],
}
```

### 2.7 Chart Keywords and Filter Regex

```python
_CHART_KEYWORDS = [
    "chart", "graph", "plot", "visualize", "visualise", "visualization",
    "bar chart", "line chart", "pie chart", "donut", "scatter", "area chart",
    "funnel chart", "trend", "show me a", "create a chart", "generate chart",
    "list charts", "my charts", "saved charts", "delete chart",
]

_CHART_FILTER_RE = re.compile(
    r"\b(bar|line|pie|donut|scatter|area|funnel)\s*(chart|graph|plot)?\b",
    re.IGNORECASE,
)
```

### 2.8 Pending Action TTL and Re-Invocation

Pending action TTL is enforced in `backend/main.py`:

```python
# Expire pending action after 300 seconds (5 minutes)
if pending_action:
    age = datetime.utcnow() - session.updated_at
    if age.total_seconds() > 300:
        pending_action = None
        session.pending_action = None
        db.commit()
```

When a confirmation is detected, the supervisor sends this directive to the specialist:

```python
confirmation_directive = (
    f"The user has confirmed the previous action. Re-execute it now using "
    f"confirmed=True with the exact same parameters shown in the WARNING:\n\n"
    f"{pending_action}"
)
```

This directive is injected as the user message so the specialist re-invokes the tool with `confirmed=True` deterministically — the LLM does not decide whether to confirm.

### 2.9 Module Tag Mapping

```python
_TAG_TO_MODULE = {
    "[CRM]":        "CRM",
    "[INVOICING]":  "INVOICING",
    "[CHART]":      "CHART",
    "[GENERAL]":    "GENERAL",
}
```

Response tags are stripped from specialist output and returned as the `module` field of the API response JSON.

### 2.10 LLM Router Prompt (Tier 2)

```
You are a routing classifier for an ERP system.
Classify the user query into exactly one of: CRM, INVOICING, CHART, GENERAL.

CRM: deals, companies, contacts, activities, pipeline, churn, sales predictions
INVOICING: invoices, billing, revenue, payments, overdue balances
CHART: charts, graphs, visualizations, plots, trends
GENERAL: greetings, help, unclear queries

Respond ONLY with JSON: {"module": "<MODULE>"}
```

### 2.11 run_agent() Flow Summary

```python
async def run_agent(message: str, session_id: str, history: list, db) -> dict:
    # 1. Load session, retrieve pending_action
    # 2. Check pending_action TTL (>300s → expire)
    # 3. Tier 0: confirmation check → confirmed=True re-invocation
    # 4. Tier 0b: context continuation (disambiguation inheritance)
    # 5. Tier 1: fast_route() keyword match
    # 6. Tier 2: LLM router (if Tier 1 → None)
    # 7. RAG context injection (CRM / INVOICING only)
    # 8. Specialist agent invocation
    # 9. Store pending_action if preview detected
    # 10. Return {response, module, session_id}
```

---

## 3. CRM Specialist Agent — Complete Tool Inventory

**File**: `backend/agents/crm_specialist.py`  
**Tools file**: `backend/tools/crm_tools.py`

### 3.1 Execution Paths (Five Tiers)

```
User message to CRM specialist
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 1: List-intent bypass (_LIST_TOOL_MAP)             │
│  Message matches a LIST_INTENT key exactly →             │
│  call tool directly, skip AgentExecutor entirely         │
└──────────────────────────────────────────────────────────┘
    │ (not a list intent)
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 2: Churn prediction shortcut                       │
│  Message matches _CHURN_FOR_RE or _CHURN_INTENTS →       │
│  extract company_name, call predict_churn directly       │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 3: Deal prediction shortcut                        │
│  Message matches _DEAL_ID_RE or _DEAL_PREDICT_INTENTS → │
│  extract deal_id, call predict_deal_win directly         │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 4: Write-op fast filter                            │
│  Message matches _WRITE_OP_RE →                          │
│  skip RAG, go directly to AgentExecutor                  │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 5: Full AgentExecutor                              │
│  max_iterations=3, create_tool_calling_agent             │
│  wrapped by safe_agent_run()                             │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Deterministic List Bypass Map (_LIST_TOOL_MAP)

```python
_LIST_TOOL_MAP: dict[str, str] = {
    # Companies
    "list companies":               "list_companies",
    "show companies":               "list_companies",
    "all companies":                "list_companies",
    "list clients":                 "list_companies",
    "show clients":                 "list_companies",
    "all clients":                  "list_companies",
    # Deals
    "list deals":                   "list_deals",
    "show deals":                   "list_deals",
    "all deals":                    "list_deals",
    "list open deals":              "list_deals",
    "show open deals":              "list_deals",
    "open deals":                   "list_deals",
    # Contacts
    "list contacts":                "list_contacts",
    "show contacts":                "list_contacts",
    "all contacts":                 "list_contacts",
    # Activities
    "list activities":              "list_activities",
    "show activities":              "list_activities",
    "all activities":               "list_activities",
    # Pipeline
    "pipeline":                     "get_pipeline_summary",
    "pipeline summary":             "get_pipeline_summary",
    "show pipeline":                "get_pipeline_summary",
    "sales pipeline":               "get_pipeline_summary",
    # At-risk / churn
    "at risk clients":              "get_at_risk_clients",
    "clients at risk":              "get_at_risk_clients",
    "at-risk clients":              "get_at_risk_clients",
    "show at risk":                 "get_at_risk_clients",
    "churn risk":                   "get_at_risk_clients",
    # Won deal value
    "total won deal value":         "get_total_won_deal_value",
    "total won value":              "get_total_won_deal_value",
    "won deal value":               "get_total_won_deal_value",
    "total won":                    "get_total_won_deal_value",
    # (35+ entries total)
}
```

### 3.3 Regex Patterns

```python
# Filter guard: prevent bypass when message contains filter terms
_BYPASS_FILTER_GUARD_RE = re.compile(
    r"\b(for|by|of|filter|where|company|client|stage|status|value|search)\b",
    re.IGNORECASE,
)

# Detect filtered list queries (e.g., "list deals for TechCorp")
_LIST_ENTITY_FILTER_RE = re.compile(
    r"\b(list|show|get)\s+(deals|companies|contacts|activities)\s+(for|by|of|from)\b",
    re.IGNORECASE,
)

# Write operations — bypass RAG
_WRITE_OP_RE = re.compile(
    r"\b(create|add|insert|update|edit|modify|delete|remove|close|cancel|mark)\b",
    re.IGNORECASE,
)

# Churn for specific company
_CHURN_FOR_RE = re.compile(
    r"\bchurn\s+(risk\s+)?(for|of)\s+(.+)",
    re.IGNORECASE,
)

# Deal ID extraction
_DEAL_ID_RE = re.compile(r"\b(?:deal\s+)?(?:id\s+)?(\d+)\b", re.IGNORECASE)
```

### 3.4 Churn & Deal Prediction Intent Sets

```python
_CHURN_INTENTS = {
    "predict churn", "churn prediction", "churn probability", "churn score",
    "will this client churn", "is this client at risk",
}

_DEAL_PREDICT_INTENTS = {
    "predict deal", "deal win probability", "will we win this deal",
    "deal prediction", "win probability", "deal win chance",
}
```

### 3.5 Agent Caching

The CRM specialist uses a module-level cached agent that is refreshed daily:

```python
_crm_agent_cache: dict = {"agent": None, "created_at": None}

def _get_or_create_crm_agent():
    now = datetime.utcnow()
    cached = _crm_agent_cache
    if cached["agent"] is None or (now - cached["created_at"]).total_seconds() > 86400:
        llm = get_llm()
        agent = create_tool_calling_agent(llm, tools, prompt)
        cached["agent"] = AgentExecutor(agent=agent, tools=tools, max_iterations=3, ...)
        cached["created_at"] = now
    return cached["agent"]
```

### 3.6 CRM Tool Inventory

#### READ Tools

| Tool | Signature | Returns | Notes |
|------|-----------|---------|-------|
| `get_total_won_deal_value` | `()` | Formatted TND string | Queries warehouse.fact_deals status='won' |
| `list_companies` | `(limit=50, search=None)` | Formatted list | DEFAULT_LIST_LIMIT=50 |
| `get_company` | `(company_name: str)` | Company detail card | ILIKE fuzzy match |
| `list_deals` | `(limit=50, status=None, company_name=None)` | Formatted list | Filterable by status/company |
| `get_deal` | `(deal_id: int)` | Deal detail card | |
| `get_pipeline_summary` | `()` | Stage breakdown table | Groups by stage, sums value |
| `list_contacts` | `(limit=50, company_name=None)` | Formatted list | |
| `list_activities` | `(limit=50, company_name=None)` | Formatted list | |
| `get_at_risk_clients` | `()` | Risk-sorted list | Uses warehouse churn signals |
| `predict_churn` | `(company_name: str)` | Churn score + factors | Delegates to `predictor.py` |
| `predict_deal_win` | `(deal_id: int)` | Win probability + factors | Delegates to `deal_predictor.py` |

#### WRITE Tools (Two-Phase Pattern)

| Tool | Signature | Preview (confirmed=False) | Execute (confirmed=True) |
|------|-----------|--------------------------|--------------------------|
| `create_company` | `(name, industry, status, phone, email, city, country, confirmed)` | Returns preview card | INSERT + log_action |
| `create_contact` | `(first_name, last_name, email, phone, company_name, role, confirmed)` | Returns preview card | INSERT + log_action |
| `create_deal` | `(title, company_name, value, stage, probability, confirmed)` | Returns preview card | INSERT + log_action |
| `update_company` | `(company_name, field, new_value, confirmed)` | Returns diff preview | UPDATE + log_action |
| `update_contact` | `(contact_id, field, new_value, confirmed)` | Returns diff preview | UPDATE + log_action |
| `update_deal` | `(deal_id, field, new_value, confirmed)` | Returns diff preview | UPDATE + log_action |
| `update_deal_status` | `(deal_id, new_status, confirmed)` | Returns status change preview | UPDATE + close_date + log_action |
| `mark_activity_done` | `(activity_id, confirmed)` | Returns confirmation preview | UPDATE done_at + log_action |
| `create_activity` | `(company_name, type, description, due_date, confirmed)` | Returns preview card | INSERT + log_action |
| `delete_company` | `(company_name, confirmed)` | Returns "will delete" preview | Soft-delete is_deleted=True + log_action |
| `delete_contact` | `(contact_id, confirmed)` | Returns "will delete" preview | Soft-delete + log_action |
| `delete_deal` | `(deal_id, confirmed)` | Returns "will delete" preview | Soft-delete + log_action |

### 3.7 Two-Phase Write Pattern (Code Snippet)

```python
@tool
def create_company(
    name: str,
    industry: str = "Other",
    status: str = "prospect",
    phone: str = "",
    email: str = "",
    city: str = "",
    country: str = "Tunisia",
    confirmed: bool = False,
) -> str:
    db = get_session()
    try:
        if not confirmed:
            return (
                f"⚠️ PREVIEW — About to create company:\n"
                f"  Name:     {name}\n"
                f"  Industry: {industry}\n"
                f"  Status:   {status}\n"
                f"  Phone:    {phone or '—'}\n"
                f"  Email:    {email or '—'}\n"
                f"  City:     {city or '—'}, {country}\n\n"
                f"Reply 'yes' to confirm or 'no' to cancel."
            )
        company = Company(
            name=name, industry=industry, status=status,
            phone=phone, email=email, city=city, country=country,
        )
        db.add(company)
        db.flush()
        log_action(db, "create", "company", company.id,
                   {"name": name, "industry": industry}, f"Created company #{company.id}")
        db.commit()
        return f"✅ Company '{name}' created successfully (ID: {company.id})."
    finally:
        db.close()
```

### 3.8 DEFAULT_LIST_LIMIT

```python
DEFAULT_LIST_LIMIT = 50
```

---

## 4. Invoicing Agent — Complete Tool Inventory

**File**: `backend/agents/invoice_specialist.py`  
**Tools file**: `backend/tools/invoice_tools.py`

### 4.1 Execution Paths

```
User message to Invoice specialist
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 1: List-intent bypass (_LIST_TOOL_MAP)             │
│  Direct tool call, skip AgentExecutor                    │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 2: Revenue direct route (_REVENUE_DIRECT_RE)       │
│  "total revenue", "revenue summary", "collection rate"  │
│  → extract time params, call get_revenue_summary()       │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  PATH 3: Full AgentExecutor (max_iterations=15)          │
│  wrapped by safe_agent_run()                             │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Revenue Direct Route Regex

```python
_REVENUE_DIRECT_RE = re.compile(
    r"\b(total revenue|revenue summary|collection rate|total invoiced|"
    r"total paid|total pending|total overdue|invoice summary)\b",
    re.IGNORECASE,
)
```

### 4.3 Time Parameter Extraction

```python
_MONTH_MAP = {
    "january": 1, "février": 2, "february": 2, "mars": 3, "march": 3,
    "april": 4, "avril": 4, "may": 5, "mai": 5, "june": 6, "juin": 6,
    "july": 7, "juillet": 7, "august": 8, "août": 8,
    "september": 9, "septembre": 9, "october": 10, "octobre": 10,
    "november": 11, "novembre": 11, "december": 12, "décembre": 12,
}

_NAMED_QUARTER_MAP = {
    "q1": (1, 3), "q2": (4, 6), "q3": (7, 9), "q4": (10, 12),
}

def _EXTRACT_TIME_PARAMS(message: str) -> dict:
    """Parse year, month, quarter from natural language message.
    Returns: {year: int|None, month: int|None, quarter: int|None}
    Examples: "last year", "Q2 2024", "in March", "this month"
    """
    ...
```

### 4.4 Invoice List Bypass Map (Selected Entries)

```python
_LIST_TOOL_MAP = {
    "list invoices":          "list_invoices",
    "show invoices":          "list_invoices",
    "all invoices":           "list_invoices",
    "overdue invoices":       "get_overdue_invoices",
    "show overdue":           "get_overdue_invoices",
    "pending invoices":       "list_invoices",    # filter=pending
    "paid invoices":          "list_invoices",    # filter=paid
    "revenue summary":        "get_revenue_summary",
    "total revenue":          "get_revenue_summary",
    ...
}
```

### 4.5 Invoice Tool Inventory

#### READ Tools

| Tool | Signature | Returns | Notes |
|------|-----------|---------|-------|
| `list_invoices` | `(limit=50, status=None, company_name=None)` | Formatted invoice list | Filterable |
| `get_invoice` | `(invoice_id: int)` | Invoice detail card | Includes line items |
| `get_revenue_summary` | `(year=None, month=None, quarter=None)` | Revenue breakdown | Queries warehouse.fact_revenue |
| `get_overdue_invoices` | `(limit=50)` | Sorted overdue list | Sorted by due_date asc |
| `get_client_balance` | `(company_name: str)` | Balance summary | paid/pending/overdue breakdown |

#### WRITE Tools

| Tool | Signature | Preview | Execute | Notes |
|------|-----------|---------|---------|-------|
| `create_invoice` | `(company_name, items, due_date, confirmed)` | Item list + totals | INSERT Invoice + InvoiceItems + log_action | `items` format: `"desc:qty:price"` pipe-separated; TVA=19.0 hardcoded |
| `mark_invoice_paid` | `(invoice_id, confirmed)` | Shows amount to mark | UPDATE status='paid', paid_at=now + log_action | |
| `send_invoice` | `(invoice_id, confirmed)` | Shows recipient email | UPDATE status='sent' + log_action | |
| `cancel_invoice` | `(invoice_id, confirmed)` | Shows invoice to cancel | UPDATE status='cancelled' + log_action | |
| `update_invoice` | `(invoice_id, field, new_value, confirmed)` | Shows diff | UPDATE + log_action | |
| `delete_invoice` | `(invoice_id, confirmed)` | Shows invoice to delete | Soft-delete is_deleted=True + log_action | |

### 4.6 Invoice Number Format

```python
invoice_number = f"INV-{year}-{count:04d}"
# Example: INV-2024-0042
```

### 4.7 TVA Rate

```python
TVA = 19.0  # Hardcoded in create_invoice(), never configurable
```

### 4.8 Invoice Item Parsing

```python
# Items string format: "description:quantity:unit_price|description:quantity:unit_price"
# Example: "Consulting services:10:500|Travel expenses:1:200"
for item_str in items_raw.split("|"):
    parts = item_str.strip().split(":")
    description = parts[0].strip()
    quantity = float(parts[1].strip())
    unit_price = float(parts[2].strip())
    subtotal = quantity * unit_price
```

---

## 5. Analytics / Chart Agent — Complete Tool Inventory

**File**: `backend/agents/chart_agent.py`  
**Tools file**: `backend/tools/chart_tools.py`

### 5.1 Fabrication Detection

```python
_FABRICATION_SUBSTRINGS = [
    "chart id:",
    "chart_id:",
    "chart saved",
    "chart created",
    "successfully created",
    "✅ chart",
    "created successfully",
    "chart titled",
]

_FABRICATION_CHART_ID_RE = re.compile(
    r"\bchart\s+(?:id\s*:?\s*)?\d+\b",
    re.IGNORECASE,
)

def _is_fabricated(response: str, intermediate_steps: list) -> bool:
    """Return True if the agent fabricated a chart creation without calling any tool."""
    if intermediate_steps:
        return False  # Tool was actually called — not fabricated
    
    resp_lower = response.lower()
    for substr in _FABRICATION_SUBSTRINGS:
        if substr in resp_lower:
            return True
    if _FABRICATION_CHART_ID_RE.search(response):
        return True
    return False
```

When fabrication is detected, the agent returns:
```
"I couldn't create the chart. Please try again with a more specific request."
```

### 5.2 Multi-Filter Complexity Guard

```python
_MULTI_FILTER_RE = re.compile(
    r"\b(filter|where|by|for)\b.+\b(and|with|also)\b.+\b(filter|where|by|for)\b",
    re.IGNORECASE,
)

_UNSUPPORTED_COMPLEXITY_MSG = (
    "I can only apply a single filter at a time. "
    "Please simplify your chart request and try again."
)
```

### 5.3 List Intent Bypass

```python
_LIST_INTENTS = {
    "list charts", "show charts", "my charts", "saved charts",
    "list saved charts", "show saved charts", "all charts",
}
```

When matched, calls `list_saved_charts()` directly, bypassing the AgentExecutor and RAG injection.

### 5.4 Chart Tool Inventory

| Tool | Signature | Returns | Notes |
|------|-----------|---------|-------|
| `generate_chart` | `(title, chart_type, data_source, x_field, y_field, filter_field=None, filter_value=None, aggregation="count", time_granularity=None)` | `"Chart '{title}' created successfully. Chart ID: {id}."` | Validates inputs, builds SQL, INSERTs into public.axis_charts |
| `list_saved_charts` | `(limit=20)` | Formatted chart list | Queries public.axis_charts |
| `delete_chart` | `(chart_id: int, confirmed=False)` | Preview or confirmation | Two-phase delete + log_action |

### 5.5 Valid Chart Types and Data Sources

```python
VALID_CHART_TYPES = {'bar', 'line', 'scatter', 'pie', 'donut', 'funnel', 'area'}

VALID_DATA_SOURCES = {'fact_deals', 'fact_revenue', 'fact_activities', 'dim_client'}
```

### 5.6 Chart Color Palette

```python
PALETTE = [
    '#6C63FF',  # indigo
    '#3ECF8E',  # green
    '#00D4FF',  # cyan
    '#FF4D4D',  # red
    '#FF9F43',  # orange
    '#A29BFE',  # light purple
    '#55EFC4',  # teal
    '#FD79A8',  # pink
]
```

### 5.7 Chart-Type-Specific Rendering Specs

| Chart Type | Special Configuration |
|------------|----------------------|
| `donut` | `hole=0.38` in Plotly layout |
| `funnel` | x and y axes swapped: `y=categories`, `x=values` |
| `pie` | Standard polar/pie layout |
| `line` | time_granularity activates DATE_TRUNC / TO_CHAR SQL grouping |
| `area` | Fill mode enabled (`fill='tozeroy'`) |

### 5.8 SQL Generation for Time-Series Charts

```python
if time_granularity == "month":
    date_expr = f"TO_CHAR(DATE_TRUNC('month', {x_field}), 'YYYY-MM')"
elif time_granularity == "quarter":
    date_expr = (
        f"'Q' || EXTRACT(QUARTER FROM {x_field})::int "
        f"|| ' ' || EXTRACT(YEAR FROM {x_field})::int"
    )
elif time_granularity == "year":
    date_expr = f"EXTRACT(YEAR FROM {x_field})::int"
```

### 5.9 Chart Storage Schema

```sql
CREATE TABLE IF NOT EXISTS public.axis_charts (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    chart_type  TEXT NOT NULL,
    data_source TEXT NOT NULL,
    chart_json  JSONB NOT NULL,       -- Plotly figure dict
    created_at  TIMESTAMP DEFAULT NOW(),
    created_by  TEXT
);
```

---

## 6. ETL Pipeline — Every Step

### 6.1 Primary: Airflow DAG

**File**: `airflow/dags/etl_jbm_pipeline.py`  
**DAG ID**: `jbm_etl_pipeline`  
**Schedule**: Manual trigger (no cron schedule in DAG)

#### 6.2 DAG Task Graph

```
extract_clients  ──► transform_clients  ──► load_clients  ──┐
extract_deals    ──► transform_deals    ──► load_deals    ──┤
extract_activities ► transform_activities ► load_activities ─┤──► populate_dim_date ──► validate_warehouse
extract_invoices ──► transform_invoices ──► load_invoices ──┘
```

#### 6.3 Step-by-Step Pipeline Details

**Steps 1–3: Clients Domain**

| Step | Function | Input | Output |
|------|----------|-------|--------|
| Extract | `extract_clients()` | `data/raw_clients.xlsx` | `data/staging/clients.csv` |
| Transform | `transform_clients()` | `data/staging/clients.csv` | `data/staging/clients_clean.csv` |
| Load | `load_clients()` | `data/staging/clients_clean.csv` | `warehouse.dim_client` (TRUNCATE + COPY) |

**Transform clients** (key operations):
- rapidfuzz deduplication: `fuzz.token_sort_ratio(n1, n2) >= 85` → keep first occurrence
- Normalize company names: strip `[*#!@]`, collapse whitespace, lowercase for comparison
- Derive `client_age_days`, `client_age_months` from `created_date`
- Map status values: `actif→active`, `inactif→inactive`, etc.

**Steps 4–6: Deals Domain**

| Step | Function | Input | Output |
|------|----------|-------|--------|
| Extract | `extract_deals()` | `data/raw_deals.xlsx` | `data/staging/deals.csv` |
| Transform | `transform_deals()` | `data/staging/deals.csv` | `data/staging/deals_clean.csv` |
| Load | `load_deals()` | `data/staging/deals_clean.csv` | `warehouse.fact_deals` (TRUNCATE + COPY) |

**Transform deals** (key operations):
- `deal_size_category`:
  - `value < 5,000` → "Small"
  - `5,000 ≤ value < 20,000` → "Medium"
  - `20,000 ≤ value < 100,000` → "Large"
  - `value ≥ 100,000` → "Enterprise"
- `quarter` format: `f"Q{(d.month-1)//3+1} {d.year}"` (e.g., "Q2 2024")
- `days_to_close` = `closed_date - created_date` (for won/lost deals)
- `deal_ref` = `f"DEAL-{id:06d}"`

**Steps 7–9: Activities Domain**

| Step | Function | Input | Output |
|------|----------|-------|--------|
| Extract | `extract_activities()` | `data/raw_activities.xlsx` | `data/staging/activities.csv` |
| Transform | `transform_activities()` | `data/staging/activities.csv` | `data/staging/activities_clean.csv` |
| Load | `load_activities()` | `data/staging/activities_clean.csv` | `warehouse.fact_activities` (TRUNCATE + COPY) |

**Transform activities** (key operations):
- Chunk processing: 50,000 rows per chunk to manage memory
- Activity type normalization: `call/appel → Appel`, `email/courriel → Email`, `meeting/réunion → Réunion`, `task → Task`, `note → Note`, `demo/démo → Démo`, `visit/visite → Visite`, `follow-up/relance → Relance`, `support → Support`, `training/formation → Formation`
- Sentiment signals from description (ILIKE keyword list):
  - Churn signals: `insatisfait`, `concurrent`, `resilie/résilié`, `annule/annulé`, `probleme/problème`, `plainte`, `bloque/bloqué`, `pas satisfait`, `decu/déçu`, `qualite trop/qualité trop`, `tarif trop`
  - Positive signals: `satisfait`, `excellent`, `renouvellement`, `recommande/recommandé`, `signe/signé`, `valide/validé`, `accord`, `ravi`, `confiant`, `upsell`, `croissance`, `partenariat`, `fidelite/fidélité`, `expansion`
- `source_id` = `f"ACT-{id:07d}"`

**Steps 10–12: Invoices Domain**

| Step | Function | Input | Output |
|------|----------|-------|--------|
| Extract | `extract_invoices()` | `data/raw_invoices.xlsx` | `data/staging/invoices.csv` |
| Transform | `transform_invoices()` | `data/staging/invoices.csv` | `data/staging/invoices_clean.csv` |
| Load | `load_invoices()` | `data/staging/invoices_clean.csv` | `warehouse.fact_revenue` (TRUNCATE + COPY) |

**Transform invoices** (key operations):
- `payment_delay_days` = `payment_date - invoice_date` (only for paid invoices)
- `is_overdue` = `due_date < TODAY AND status NOT IN ('paid', 'cancelled')`
- `days_outstanding` = `TODAY - invoice_date` (for non-paid, non-cancelled)
- `amount_paid` = `total_amount` if status='paid', else 0

**Step 13: dim_date Population**

```python
def populate_dim_date():
    """Generate date spine from 2020-01-01 to today+2 years."""
    # For each date: date_key, year, quarter, month, month_name,
    # week_of_year, day_of_week, day_name, is_weekend, fiscal_year
```

**Step 14: Warehouse Validation**

```python
VALIDATION_THRESHOLDS = {
    "dim_client":      500,     # Minimum expected rows
    "fact_deals":    3_000,
    "fact_activities": 50_000,
    "fact_revenue":    500,
    "dim_date":      1_000,
}

WIN_RATE_BOUNDS = (10.0, 90.0)  # Percent — flags data quality issues
```

If any threshold is violated, the validation task raises `AirflowSkipException` (logs warning but doesn't fail the DAG).

### 6.4 Load Strategy

```python
# TRUNCATE + COPY (not UPSERT) — fast bulk reload
conn.execute(f"TRUNCATE warehouse.{table_name} RESTART IDENTITY CASCADE")
# Then COPY via psycopg2 copy_expert() from StringIO CSV
```

### 6.5 Standalone ETL Runner

**File**: `backend/etl/run_etl.py`

Mocks Airflow modules (`DAG`, `PythonOperator`, `EmptyOperator`) at import time so `etl_jbm_pipeline.py` can be loaded without an Airflow installation. Runs all 14 steps sequentially with timing summary.

```python
# Airflow mock injection
sys.modules["airflow"] = ...
sys.modules["airflow.operators.python"] = ...
sys.modules["airflow.operators.empty"] = ...

import etl_jbm_pipeline as _etl

_etl.DATA_DIR = DATA_DIR          # Override Airflow container paths
_etl.STAGING_DIR = STAGING_DIR
_etl.DATABASE_URL = os.getenv("DATABASE_URL")
```

### 6.6 Legacy ETL (DEPRECATED)

**File**: `backend/etl/etl_pipeline.py`  
Uses SQLAlchemy ORM (not raw SQL COPY), truncate-and-reload, no rapidfuzz deduplication. Contains warehouse table DDL and `STAGE_MAP` normalization. Not used in production — replaced by Airflow DAG.

### 6.7 Alternative: Direct SQL Rebuild

**File**: `rebuild_warehouse.sql`  
Pure SQL denormalization directly from `public.*` operational tables to `warehouse.*`. Does not require CSV files or ETL tooling. Used for emergency rebuilds after company cleanup migrations.

Expected row counts (comment in SQL):
- `dim_client`: 359
- `fact_deals`: ~7,713
- `fact_revenue`: ~2,226
- `fact_activities`: ~47,052

### 6.8 Company Name Normalization

Three independent locations must be kept in sync (per `tasks/lessons.md`):

| Location | Mechanism |
|----------|-----------|
| `data/populate_operational.py` | `_normalize_company_name()` Python function |
| `cleanup_companies.sql` | `REGEXP_REPLACE(name, '[*#!@]', '', 'g')` + whitespace collapse |
| `airflow/dags/etl_jbm_pipeline.py:460` | rapidfuzz token_sort_ratio, threshold=85 |

**Current character set** (as of 2026-04-16): `[*#!@]`  
Source: `generate_raw_data.py:168` and `:791` — injected during synthetic data generation.

---

## 7. RAG System — Complete Implementation

### 7.1 Architecture

```
Warehouse tables (warehouse.*)
        │
        ▼ run_full_pipeline()
OllamaEmbeddings (nomic-embed-text, 768-dim)
        │
        ▼ batch=25, chunk_size=500, overlap=50
ChromaDB persistent store (./chroma_db/)
    ├── Collection: jbm_crm       (cosine similarity)
    └── Collection: jbm_invoicing (cosine similarity)
        │
        ▼ ERPRetriever.retrieve()
Top-K=5 chunks + company-specific filter
        │
        ▼
Injected as system context before agent invocation
```

### 7.2 Embedding Model

| Parameter | Value |
|-----------|-------|
| Model | `nomic-embed-text` |
| Provider | Ollama (local) |
| Dimensions | 768 |
| Similarity metric | Cosine |

### 7.3 Collections and Source Tables

| Collection | Source Tables | Content |
|------------|--------------|---------|
| `jbm_crm` | `warehouse.dim_client`, `warehouse.fact_deals`, `warehouse.fact_activities` | Company profiles, deal histories, activity logs |
| `jbm_invoicing` | `warehouse.fact_revenue` | Invoice records, payment histories |

**Critical rule**: Source is **warehouse tables only** (`warehouse.*`). Operational tables (`public.*`) are never embedded.

### 7.4 ERPRetriever Class

**File**: `backend/rag/retriever.py`

```python
class ERPRetriever:
    def __init__(self, collection_name: str, top_k: int = 5):
        self.collection = chromadb_client.get_collection(collection_name)
        self.embedder = OllamaEmbeddings(model="nomic-embed-text")
        self.top_k = top_k

    def retrieve(self, query: str) -> list[dict]:
        """Top-K retrieval by cosine similarity."""
        query_embedding = self.embedder.embed_query(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k,
            include=["documents", "metadatas", "distances"],
        )
        return results

    def retrieve_for_company(self, query: str, company_name: str) -> list[dict]:
        """Company-specific retrieval using ChromaDB metadata filter."""
        query_embedding = self.embedder.embed_query(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k,
            where={"company_name": {"$eq": company_name}},
            include=["documents", "metadatas", "distances"],
        )
        return results

    def format_context(self, results: list[dict]) -> str:
        """Format retrieved chunks with similarity score and source metadata."""
        formatted = []
        for doc, meta, dist in zip(results["documents"][0],
                                    results["metadatas"][0],
                                    results["distances"][0]):
            similarity = 1.0 - dist  # Convert distance to similarity
            formatted.append(
                f"[Source: {meta.get('source', 'unknown')} | "
                f"Company: {meta.get('company_name', '?')} | "
                f"Score: {similarity:.3f}]\n{doc}"
            )
        return "\n\n".join(formatted)
```

### 7.5 Embedding Pipeline

**File**: `backend/rag/embedding_pipeline.py`

```python
EMBED_BATCH = 25       # Documents per embedding call
CHUNK_SIZE  = 500      # Characters per text chunk
CHUNK_OVERLAP = 50     # Character overlap between chunks

def run_full_pipeline():
    """Clear all collections and rebuild from warehouse tables."""
    # 1. Drop and recreate ChromaDB collections
    # 2. Fetch all warehouse data
    # 3. Filter activities: description length > 50, not placeholder text
    # 4. Chunk documents
    # 5. Embed in batches of EMBED_BATCH
    # 6. Upsert to ChromaDB

def run_incremental_update():
    """Add only records from the last 24 hours."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    # Query warehouse for records created after cutoff
    # Embed and add (no clear, no duplicates — ChromaDB upsert by ID)
```

### 7.6 Activity Filtering for Embeddings

```python
# Only embed activities that have meaningful descriptions
if len(description) > 50 and description not in PLACEHOLDER_TEXTS:
    embed_this_activity = True
```

### 7.7 RAG Bypass for List Queries

All three specialists guard against RAG for list-intent queries:

```python
if normalized_message in _LIST_INTENTS:
    # Skip RAG retrieval entirely — return direct tool call result
    # Reason: nearest-neighbor for "list invoices" returns random company
    # context that causes the agent to filter on the wrong company
    return direct_tool_result
```

This prevents the known issue where retriever returns ~0.4 cosine similarity noise and the model treats those company names as filters.

---

## 8. Authentication & User Management

### 8.1 JWT Configuration

**File**: `backend/auth.py`

```python
SECRET_KEY = "axis-secret-key-jbm-consulting-2024"   # In code
# Note: .env overrides with SECRET_KEY="supersecretkey123" (supersedes code value)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8    # Code value (8 hours)
# Note: .env has ACCESS_TOKEN_EXPIRE_MINUTES=60 (60 minutes) — .env wins at runtime
```

### 8.2 Auth Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `verify_password` | `(plain, hashed) → bool` | bcrypt verification |
| `hash_password` | `(password) → str` | bcrypt hashing |
| `create_access_token` | `(data: dict) → str` | JWT HS256 creation |
| `decode_token` | `(token: str) → dict` | JWT decode + validation |
| `get_current_user` | `(token: str, db) → User` | FastAPI dependency |
| `require_admin` | `(current_user: User) → User` | Admin-only gate |

### 8.3 Login Flow

```
POST /api/auth/login
    │ {username, password}
    ▼
verify_password(plain, user.hashed_password)
    │
    ▼ success
create_access_token({"sub": username, "role": user.role})
    │
    ▼
{access_token, token_type: "bearer", role, full_name}
```

Token stored in browser `sessionStorage` as `axis_token`. Auto-logout on 401.

### 8.4 User Provisioning

**Endpoint**: `POST /api/axis/admin/users` (admin only)

```python
# Password generation
password = secrets.token_urlsafe(9)   # ~12-character random base64url

# Credential delivery
send_credentials_email(email=user_email, username=username, password=password)
# Uses SMTP via Gmail (SMTP_EMAIL, SMTP_APP_PASSWORD from .env)
```

### 8.5 Default Seeded Users

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | admin |
| `manager1` | `pass123` | user |
| `agent1` | `pass123` | user |

### 8.6 User Model

```python
class User(Base):
    __tablename__ = "users"
    id           = Column(Integer, primary_key=True)
    username     = Column(String, unique=True, nullable=False)
    email        = Column(String, unique=True)
    full_name    = Column(String)
    hashed_password = Column(String, nullable=False)
    role         = Column(String, default="user")   # "admin" | "user"
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
```

### 8.7 Role-Based UI Visibility

```javascript
// Admin-only nav items shown after login
if (role === 'admin') {
    document.getElementById('nav-evaluation').style.display = 'flex';
    document.getElementById('nav-users').style.display = 'flex';
}
```

Non-admin users see: Dashboard, Agent, Activity, Charts.  
Admin users additionally see: Evaluation, Users.

---

## 9. Machine Learning Models

### 9.1 Churn Model

**File**: `backend/ml/churn_model.py`  
**Artifacts**: `churn_model.joblib`, `scaler.joblib`, `feature_names.joblib`

#### 9.1.1 Feature Engineering

**Source tables**: `warehouse.dim_client`, `warehouse.fact_activities`, `warehouse.fact_deals`, `warehouse.fact_revenue`

| Feature Group | Features |
|--------------|---------|
| **Client profile** | `industry` (one-hot), `status` (one-hot), `client_age_days` |
| **Activity signals** | `total_activities`, `churn_signal_count`, `positive_signal_count`, `act_appel`, `act_email`, `act_reunion`, `act_task` |
| **Derived activity** | `activity_frequency = total_activities / client_age_months`, `churn_signal_ratio = churn_signal_count / total_activities` |
| **Deal metrics** | `total_deals`, `won_deals`, `lost_deals`, `open_deals`, `avg_deal_value`, `total_deal_value`, `avg_days_to_close`, `win_rate` |
| **Revenue metrics** | `total_invoiced`, `total_paid`, `avg_payment_delay`, `overdue_count`, `total_invoices`, `payment_rate`, `overdue_ratio` |

**Dropped at training time**: `company_name`, `client_age_months`, `total_interactions`, `churn` (label), `days_since_last_activity`

#### 9.1.2 Label Definition

```python
def _compute_churn_labels(df: pd.DataFrame, threshold_days: int) -> pd.Series:
    """
    Client is churned (label=1) if:
      - status IN ('inactive', 'churned') AND days_since_last_activity > threshold_days
    
    threshold_days auto-adjusted to achieve target churn rate of 20–35%:
      - Start: 180 days
      - Step: ±15–20 days
      - Bounds: 30–365 days
    """
```

#### 9.1.3 Encoding and Split

```python
# One-hot encoding
df = pd.get_dummies(df, columns=["industry", "status"], dummy_na=False)

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)
```

#### 9.1.4 Candidate Models

```python
candidates = {
    "LogisticRegression": LogisticRegression(max_iter=1000, random_state=42),
    "RandomForest":        RandomForestClassifier(n_estimators=100, random_state=42),
    "XGBoost":             XGBClassifier(n_estimators=100, random_state=42, eval_metric='logloss'),
}
```

Cross-validation: `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`  
Best model selection: highest F1 score.

#### 9.1.5 Calibration

```python
best_model_calibrated = CalibratedClassifierCV(
    best_model,
    cv=5,
    method='sigmoid'   # Platt scaling
)
best_model_calibrated.fit(X_train_scaled, y_train)
```

#### 9.1.6 Temperature Scaling (Post-Calibration)

```python
def _apply_temperature_scaling(prob: float) -> float:
    """Churn: compress probabilities toward 0.5 (reduce overconfidence)."""
    return 0.5 + (prob - 0.5) * 0.75
```

#### 9.1.7 Inference

**File**: `backend/ml/predictor.py`

```python
def predict_company_churn(company_name: str) -> dict:
    # 1. Exact ILIKE lookup in warehouse.dim_client
    # 2. Fuzzy fallback if exact not found
    # 3. Build feature vector (same order as feature_names.joblib)
    # 4. Scale with scaler.joblib
    # 5. predict_proba → apply temperature scaling
    # 6. Compute top-5 contributing factors (feature importance × feature value)
    return {
        "company": company_name,
        "churn_probability": float,  # 0.0–1.0
        "risk_level": "High|Medium|Low",
        "top_factors": list[dict],
    }
```

Risk thresholds:
- `≥ 0.65` → High
- `0.35–0.65` → Medium
- `< 0.35` → Low

### 9.2 Deal Win Model

**File**: `backend/ml/deal_model.py`  
**Artifacts**: `deal_model.joblib`, `deal_scaler.joblib`, `deal_feature_names.joblib`

#### 9.2.1 Feature Engineering

**Source**: Terminal deals only (`status IN ('won', 'lost')`) from `warehouse.fact_deals` + joined company metrics.

| Feature | Source | Notes |
|---------|--------|-------|
| `value_tnd` | fact_deals | Deal value |
| `stage` | fact_deals | One-hot encoded |
| `days_to_close` | fact_deals | days_to_close from warehouse |
| `deal_size_category` | fact_deals | Small/Medium/Large/Enterprise (one-hot) |
| `quarter` | fact_deals | Q1–Q4 (one-hot) |
| `industry` | dim_client join | One-hot encoded |
| `client_status` | dim_client join | One-hot encoded |
| `client_age_days` | dim_client join | |
| `company_total_activities` | fact_activities agg | |
| `company_churn_signals` | fact_activities agg | |
| `company_positive_signals` | fact_activities agg | |
| `company_activity_frequency` | derived | total_activities / client_age_months |
| `company_historical_win_rate` | leave-one-out | See anti-leakage note below |
| `company_total_deals` | fact_deals agg | |
| `company_avg_deal_value` | fact_deals agg | |
| `company_payment_rate` | fact_revenue agg | |
| `company_avg_payment_delay` | fact_revenue agg | |
| `company_overdue_ratio` | fact_revenue agg | |

**Dropped at training time**: `deal_id`, `company_name`, `status`, `probability`, `client_age_months`, `label`, `company_total_invoiced`, `company_total_paid`, `company_overdue_count`, `company_total_invoices`

#### 9.2.2 Anti-Leakage: Leave-One-Out Win Rate

```python
def _compute_loocv_win_rate(df: pd.DataFrame) -> pd.Series:
    """
    Prevent target leakage: compute each company's historical win rate
    EXCLUDING the current deal being evaluated.
    
    For deal i of company C:
        win_rate = (total_won_for_C - (1 if deal_i is won else 0)) 
                 / (total_deals_for_C - 1)
    
    Returns NaN if company has only one deal (no history available).
    """
```

#### 9.2.3 Best Model Selection

```python
# Hardcoded in deal_model.py (result of empirical evaluation)
best_name = "RandomForest"
```

#### 9.2.4 Temperature Scaling

```python
def _apply_temperature_scaling(prob: float) -> float:
    """Deal win: slightly less compression than churn."""
    return 0.5 + (prob - 0.5) * 0.55
```

#### 9.2.5 Inference

**File**: `backend/ml/deal_predictor.py`

```python
def predict_deal_outcome(deal_id: int) -> dict:
    # 1. Fetch deal from warehouse.fact_deals
    # 2. If already closed (won/lost): return actual outcome, no prediction
    # 3. Build single-row feature vector matching deal_feature_names.joblib
    # 4. Scale with deal_scaler.joblib
    # 5. predict_proba → apply temperature scaling
    # 6. Compute top-5 contributing factors
    return {
        "deal_id": int,
        "deal_title": str,
        "company": str,
        "win_probability": float,
        "outcome_prediction": "Won|Lost",
        "top_factors": list[dict],
    }
```

Threshold: `win_probability ≥ 0.5` → "Won", else "Lost"

### 9.3 Batch ML Predictions for Predictive Charts

**File**: `backend/tools/prediction_charts.py`

```python
def get_all_churn_predictions() -> list[dict]:
    """
    Load churn model artifacts, build full feature matrix for all active clients,
    batch predict_proba, apply temperature scaling.
    Returns: sorted by probability DESC.
    """

def get_all_deal_predictions() -> list[dict]:
    """
    Load deal model, fetch all open deals, batch feature construction,
    batch predict_proba, apply temperature scaling.
    Returns: sorted by win_probability DESC.
    """
```

---

## 10. Frontend & UI — Complete Feature Map

**File**: `static/axis.html`  
**Tech stack**: Vanilla JavaScript, Plotly.js 2.27.0, marked.min.js, DOMPurify 3, Google Fonts (Inter)

### 10.1 Design System

| Element | Value |
|---------|-------|
| Background | `#0A0A0A` |
| Surface | `#111111` |
| Card | `#1A1A1A` |
| Border | `#1E1E1E` |
| Primary | `#6C63FF` (indigo) |
| Success | `#3ECF8E` (green) |
| Info | `#00D4FF` (cyan) |
| Danger | `#FF4D4D` (red) |
| Warning | `#FF9F43` (orange) |
| Text | `#F0F0F0` |
| Muted | `#666666` |
| Font | Inter (300–700 weights) |

### 10.2 Application Views

| View ID | Nav Label | Visibility | Description |
|---------|-----------|------------|-------------|
| `view-dashboard` | Dashboard | All users | KPI cards + charts (Sales / Finance tabs) |
| `view-agent` | Agent | All users | Chat interface + sub-agent status panel |
| `view-activity` | Activity | All users | System audit log table |
| `view-charts` | Charts | All users | Saved charts grid with type filter |
| `view-evaluation` | Evaluation | Admin only | LLM-as-Judge eval results + conversation panel |
| `view-users` | Users | Admin only | User provisioning + user management table |

### 10.3 Dashboard — Sales Tab

**KPI Cards** (4):
| KPI | Field | Format |
|-----|-------|--------|
| Total Revenue (Paid) | `total_revenue` | TND (K/M suffix) |
| Total Deals | `total_deals` | Integer |
| Win Rate | `win_rate` | % (green) |
| Active Pipeline | `pipeline_value` | TND (green) |

**Charts** (5):
| Chart ID | Title | Type | Notes |
|----------|-------|------|-------|
| `chart-revenue-trend` | Monthly Revenue Trend | Line | DATE_TRUNC by month |
| `chart-win-rate` | Win Rate by Quarter | Bar | Per-quarter grouping |
| `chart-pipeline` | Pipeline by Stage | Donut | `hole=0.38` |
| `chart-top-clients` | Top 10 Clients by Won Deal Value | Horizontal Bar | tall height |
| `chart-new-vs-closed` | New Deals vs Closed Deals | Grouped Bar | tall height |
| `chart-deal-size` | Deal Size Distribution | Bar | Small/Medium/Large/Enterprise |

### 10.4 Dashboard — Finance & Invoicing Tab

**KPI Cards** (4):
| KPI | Field | Format |
|-----|-------|--------|
| Total Collected | `total_collected` | TND (green) |
| Total Pending | `total_pending` | TND |
| Total Overdue | `total_overdue` | TND (red) |
| Collection Rate | `collection_rate` | % (green) |

**Charts** (5):
| Chart ID | Title |
|----------|-------|
| `chart-rev-year` | Revenue by Year |
| `chart-cumulative` | Cumulative Revenue |
| `chart-payment-delay` | Payment Delay Distribution |
| `chart-status-dist` | Invoice Status Distribution |
| `chart-fin-top-clients` | Top 10 Clients by Invoice Value |
| `chart-monthly-activity` | Monthly Invoicing Activity |

### 10.5 Agent Chat Interface

**Components**:
- Chat bubble rendering with marked.js (Markdown) + DOMPurify (XSS sanitization)
- Module tags: `[CRM]→.tag-sales`, `[INVOICING]→.tag-finance`, `[CHART]→.tag-data`, `[GENERAL]→.tag-orchestrator`
- Typing indicator (3-dot bounce animation)
- Confirm/Cancel buttons rendered inline when agent returns a preview (`⚠️ PREVIEW`)
- Sub-agent status panel (right column) with animated dots: Sales Intelligence, Finance, Data Analyst, Orchestrator

**Confirm/Cancel button detection**:
```javascript
// Detect preview responses containing ⚠️ or "PREVIEW"
if (response.includes('⚠️') || response.includes('PREVIEW')) {
    renderConfirmButtons();
}
```

**Session management**:
- `session_id` = `"session_" + Date.now()` (generated once per page load)
- Sent with every `/chat` POST
- `POST /chat` → `{message, session_id}`

### 10.6 My Charts View

- Grid layout (2 columns, responsive to 1 on narrow screens)
- Filter buttons: All Time / This Year / This Quarter / This Month
- Charts rendered with Plotly from stored `chart_json` (Plotly figure dict)
- Delete button per card (two-phase: sends DELETE to `/api/axis/charts/{id}`)
- Toast notification when chart is saved from Agent view
- Expand modal for full-screen chart view (`#chart-modal-backdrop`)

### 10.7 Activity Feed (Right Panel)

- Collapsible overlay panel (right edge, toggle button with left arrow)
- Polls `/api/axis/activity-feed` every ~5 seconds when open
- Color-coded dots: add=green, update=cyan, delete=red, etl=purple
- Shows entity type, action, details (truncated), timestamp

### 10.8 Activity Log View

- Full table: Timestamp, Action, Entity, Details, Status (success/error badge)
- Fetches from `/api/axis/activity` on navigate

### 10.9 ETL Controls (Topbar)

- ETL trigger button: `POST /api/axis/etl/trigger` (admin only)
- Status indicator dot: idle=gray, running=cyan pulse, success=green, failed=red
- Polls ETL status while running

### 10.10 Evaluation View (Admin)

**Components**:
- Summary stat cards: Total Evaluated, Average Score, Pass Rate
- Left panel: Recent Conversations (collapsible per-session, per-exchange eval button)
- Right panel: Evaluation Results table (Question, Score, Task, Tool, Intent, Verdict, Notes)
- Per-exchange evaluation: SSE streaming via `GET /api/axis/evaluation/stream/{session_id}/{exchange_idx}`
- Per-session evaluation: `POST /api/axis/evaluation/run-session/{session_id}`
- Metric progress bars for 8 metrics with color coding (good=green, mid=yellow, bad=red)
- Verdict badges: PASS=green, PARTIAL=yellow, FAIL=red

### 10.11 User Management View (Admin)

- Provision form: Email, Full Name, Role (user/admin)
- `POST /api/axis/admin/users` → generates random password, sends credentials via SMTP
- User table: ID, Username, Full Name, Role badge, Created, Delete button

### 10.12 JavaScript State Object

```javascript
const state = {
    view:          'dashboard',    // Current active view
    dashTab:       'crm',          // Current dashboard tab
    user:          null,           // Logged-in username
    role:          null,           // 'admin' | 'user'
    fullName:      null,           // Display name
    etlStatus:     'idle',         // idle|running|success|failed
    etlPollTimer:  null,           // setInterval handle
    feedPollTimer: null,           // Activity feed poll handle
    activityData:  [],             // Cached activity log
    feedData:      [],             // Cached activity feed
    chartsFilter:  'all',          // Charts time filter
    crmLoaded:     false,          // Dashboard lazy-load flag
    finLoaded:     false,          // Dashboard lazy-load flag
};
```

### 10.13 Number Formatting

```javascript
function fmt(n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: 1 });
}
```

### 10.14 Plotly Base Configuration

```javascript
const PLOTLY_BASE = {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font: { color: '#F0F0F0', family: 'Inter, sans-serif', size: 11 },
    margin: { l: 80, r: 30, t: 40, b: 60, pad: 0 },
    xaxis: { gridcolor: '#1E1E1E', linecolor: '#1E1E1E', ... },
    yaxis: { gridcolor: '#1E1E1E', linecolor: '#1E1E1E', ... },
    hovermode: 'x unified',
};

const PLOTLY_CFG = { displayModeBar: false, responsive: true };
```

---

## 11. Error Handling — Complete Architecture

**File**: `backend/error_handler.py`

### 11.1 ERPErrorType Enum (14 Values)

```python
class ERPErrorType(Enum):
    DATABASE_ERROR       = "database_error"
    NOT_FOUND            = "not_found"
    VALIDATION_ERROR     = "validation_error"
    AGENT_ERROR          = "agent_error"
    TOOL_ERROR           = "tool_error"
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR  = "authorization_error"
    EXTERNAL_API_ERROR   = "external_api_error"
    RATE_LIMIT_ERROR     = "rate_limit_error"
    TIMEOUT_ERROR        = "timeout_error"
    CONFIGURATION_ERROR  = "configuration_error"
    UNKNOWN_ERROR        = "unknown_error"
    INPUT_TOO_LONG       = "input_too_long"
    EMPTY_INPUT          = "empty_input"
```

### 11.2 ERPError Exception Class

```python
class ERPError(Exception):
    def __init__(self, error_type: ERPErrorType, detail: str = "", user_message: str = ""):
        self.error_type   = error_type
        self.detail       = detail
        self.user_message = user_message or USER_MESSAGES.get(error_type, "An error occurred.")
```

### 11.3 User-Facing Messages

```python
USER_MESSAGES = {
    ERPErrorType.DATABASE_ERROR:       "There was a problem accessing the database. Please try again.",
    ERPErrorType.NOT_FOUND:            "The requested resource was not found.",
    ERPErrorType.VALIDATION_ERROR:     "The provided data is invalid. Please check your input.",
    ERPErrorType.AGENT_ERROR:          "The AI agent encountered an error. Please try again.",
    ERPErrorType.TOOL_ERROR:           "A tool failed to execute. Please try again.",
    ERPErrorType.AUTHENTICATION_ERROR: "Authentication failed. Please log in again.",
    ERPErrorType.AUTHORIZATION_ERROR:  "You don't have permission to perform this action.",
    ERPErrorType.EXTERNAL_API_ERROR:   "An external service is unavailable.",
    ERPErrorType.RATE_LIMIT_ERROR:     "Too many requests. Please wait a moment.",
    ERPErrorType.TIMEOUT_ERROR:        "The operation timed out. Please try again.",
    ERPErrorType.CONFIGURATION_ERROR:  "System configuration error. Please contact support.",
    ERPErrorType.UNKNOWN_ERROR:        "An unexpected error occurred. Please try again.",
    ERPErrorType.INPUT_TOO_LONG:       "Your message is too long. Please keep it under 2000 characters.",
    ERPErrorType.EMPTY_INPUT:          "Please enter a message.",
}
```

### 11.4 Error Handling Functions

| Function | Signature | Behavior |
|----------|-----------|---------|
| `handle_db_error` | `(exc: Exception) → ERPError` | Wraps SQLAlchemy errors with DATABASE_ERROR |
| `handle_tool_error` | `(tool_name: str, exc: Exception) → str` | Returns user-safe string, logs detail |
| `handle_agent_error` | `(exc: Exception) → str` | Returns user-safe AGENT_ERROR message |
| `validate_user_input` | `(message: str) → None` | Raises ERPError for empty/too-long |

### 11.5 Input Validation

```python
def validate_user_input(message: str) -> None:
    if not message or not message.strip():
        raise ERPError(ERPErrorType.EMPTY_INPUT)
    if len(message) > 2000:
        raise ERPError(ERPErrorType.INPUT_TOO_LONG)
```

### 11.6 Retry Decorator

```python
@with_retry(max_attempts=3, delay=1.0, exceptions=(ExternalAPIError,))
async def call_external_service():
    ...
```

### 11.7 Tool Interceptor (safe_agent_run)

**File**: `backend/agents/tool_interceptor.py`

The tool interceptor wraps every specialist agent execution to handle the case where `qwen2.5:7b` (a 7B parameter model) outputs raw JSON tool-call syntax instead of calling the tool.

#### 11.7.1 _extract_tool_call() — 4-Strategy Cascade

```python
def _extract_tool_call(response: str) -> dict | None:
    """
    Strategy 1: Parse as top-level JSON {"name": ..., "arguments": ...}
    Strategy 2: Regex extract JSON block from response text
    Strategy 3: Parse LangChain-style tool call format
    Strategy 4: Extract from markdown code fences
    Returns: {"name": tool_name, "arguments": dict} or None
    """
```

#### 11.7.2 Formatter Registry (_FORMATTERS)

```python
_FORMATTERS: dict[str, Callable] = {
    "list_companies":       _fmt_list_companies,
    "list_deals":           _fmt_list_deals,
    "list_contacts":        _fmt_list_contacts,
    "list_invoices":        _fmt_list_invoices,
    "list_activities":      _fmt_list_activities,
    "get_pipeline_summary": _fmt_pipeline_summary,
    "get_revenue_summary":  _fmt_revenue_summary,
    # ... (all list tools that need deterministic field ordering)
}
```

Formatters fire after `AgentExecutor` finishes (not mid-loop), so multi-step chains still see structured tool returns. The LLM's synthesis is bypassed only for the final user-facing output of list queries.

#### 11.7.3 Hallucinated Confirmation Detection

```python
_HALLUCINATED_CONFIRM_RE = re.compile(
    r"(confirmed|executed|done|completed|created|updated|deleted)\s*"
    r"(successfully|✅|—|:)",
    re.IGNORECASE,
)
```

If the agent produces a hallucinated confirmation on `confirmed=False`, the interceptor catches it and stores it as a pending action instead of executing.

#### 11.7.4 safe_agent_run() Logic

```python
async def safe_agent_run(agent_executor, input_dict: dict) -> str:
    try:
        result = await agent_executor.ainvoke(input_dict)
        output = result.get("output", "")
        
        # Check for fabricated tool call output
        tool_call = _extract_tool_call(output)
        if tool_call:
            # Execute the extracted tool call directly
            tool_name = tool_call["name"]
            tool_args = tool_call["arguments"]
            tool = _find_tool(agent_executor.tools, tool_name)
            return tool.invoke(tool_args)
        
        # Apply formatter if applicable
        if tool_name in _FORMATTERS:
            raw_result = tool.invoke(tool_args)
            return _FORMATTERS[tool_name](raw_result)
        
        return output
    except Exception as e:
        return handle_agent_error(e)
```

### 11.8 Pending Action Storage

```python
# Session model columns (added in startup migration)
class Session(Base):
    pending_action = Column(Text, nullable=True)    # Serialized action preview
    tool_calls     = Column(Text, nullable=True)    # JSON list of tool calls
    rag_context    = Column(Text, nullable=True)    # Injected RAG context text
```

---

## 12. Docker & Deployment

### 12.1 docker-compose.yml — Service Definitions

```yaml
version: '3.8'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: erp_user
      POSTGRES_PASSWORD: erp_pass
      POSTGRES_DB: erp_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U erp_user -d erp_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      DATABASE_URL: postgresql://erp_user:erp_pass@db:5432/erp_db
    volumes:
      - ./backend:/app/backend   # Hot-reload mount
    depends_on:
      db:
        condition: service_healthy
    command: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  postgres_data:
```

### 12.2 Airflow Compose (docker-compose.airflow.yml)

Defines: `airflow-webserver`, `airflow-scheduler`, `airflow-worker`, `airflow-db` (PostgreSQL for Airflow metadata).  
Access: `http://localhost:8080`

### 12.3 Quick Reference Commands

| Task | Command |
|------|---------|
| Start full stack | `docker-compose up --build` |
| Local API (no Docker) | `uvicorn backend.main:app --reload --port 8000` |
| Seed database | `python -m backend.seed.seed_jbm` |
| Run ETL (standalone) | `python -m backend.etl.run_etl` |
| Run ETL (Airflow) | `start_airflow.bat` → trigger via UI |
| Setup RAG | `python -m backend.rag.setup_rag` |
| Incremental RAG | `python -m backend.rag.embedding_pipeline run_incremental_update` |
| Run dashboards | `streamlit run dashboards/main.py` |
| Train churn model | `python backend/ml/churn_model.py` |
| Train deal model | `python backend/ml/deal_model.py` |

### 12.4 API Endpoints Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/login` | None | JWT login |
| `POST` | `/chat` | Bearer | Main agent chat endpoint |
| `GET` | `/health` | None | Health check |
| `GET` | `/api/axis/dashboard/crm` | Bearer | CRM KPI metrics |
| `GET` | `/api/axis/dashboard/finance` | Bearer | Finance KPI metrics |
| `GET` | `/api/axis/activity` | Bearer | Full audit log |
| `GET` | `/api/axis/activity-feed` | Bearer | Recent activity feed (last 20) |
| `GET` | `/api/axis/charts` | Bearer | List saved charts |
| `DELETE` | `/api/axis/charts/{id}` | Bearer | Delete saved chart |
| `POST` | `/api/axis/etl/trigger` | Admin | Trigger ETL pipeline |
| `GET` | `/api/axis/etl/status` | Bearer | ETL run status |
| `POST` | `/api/axis/admin/users` | Admin | Provision new user |
| `GET` | `/api/axis/admin/users` | Admin | List all users |
| `DELETE` | `/api/axis/admin/users/{id}` | Admin | Delete user |
| `GET` | `/api/axis/evaluation/conversations` | Admin | List sessions with history |
| `POST` | `/api/axis/evaluation/run-session/{session_id}` | Admin | Run per-session evaluation |
| `GET` | `/api/axis/evaluation/stream/{session_id}/{idx}` | Admin | SSE streaming eval |
| `GET` | `/api/axis/evaluation/results` | Admin | Get stored eval results |

### 12.5 Startup Migrations

On every server start, `backend/main.py` runs:

```python
@app.on_event("startup")
async def startup():
    Base.metadata.create_all(bind=engine)
    
    # Add missing columns to sessions table (idempotent)
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pending_action TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS tool_calls TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS rag_context TEXT"
        ))
        conn.commit()
```

---

## 13. LLM Selection & All Models Used

### 13.1 Primary LLM

**File**: `backend/agents/llm.py`

```python
ERP_MODEL = "qwen2.5:7b"

def get_llm(temperature: float = 0) -> ChatOllama:
    return ChatOllama(
        model=ERP_MODEL,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=temperature,
    )
```

| Parameter | Value |
|-----------|-------|
| Model | `qwen2.5:7b` |
| Provider | Ollama (local inference) |
| Temperature | `0` (deterministic) |
| Protocol | Ollama REST API (`/api/chat`) |
| Base URL | `OLLAMA_BASE_URL` env var (default: `http://localhost:11434`) |

### 13.2 All Models in Use

| Model | File | Role | Protocol |
|-------|------|------|---------|
| `qwen2.5:7b` | `backend/agents/llm.py` | ALL agents: CRM, INVOICING, CHART, Supervisor | Ollama ChatOllama |
| `qwen2.5:7b` | `backend/evaluation/evaluator.py` | LLM-as-Judge evaluation | Ollama `/api/generate` |
| `nomic-embed-text` | `backend/rag/embedding_pipeline.py` | Text embeddings (768-dim) for ChromaDB | Ollama OllamaEmbeddings |

**Important constraints** (from CLAUDE.md):
- No other LLM providers. Ollama only.
- No other models. `qwen2.5:7b` + `nomic-embed-text` fixed.
- `ChatOllama` never constructed directly in agent files — always via `get_llm()`.

### 13.3 Evaluation Judge Configuration

```python
JUDGE_MODEL = "qwen2.5:7b"
OLLAMA_URL  = "http://localhost:11434/api/generate"
```

Judge prompt format:
```
Score 0–100 based on: factual correctness, completeness, relevance.
Respond ONLY with JSON: {"score": <0-100>, "verdict": "PASS|PARTIAL|FAIL", "reasoning": "<one sentence>"}
PASS = score >= 70
PARTIAL = score 40-69
FAIL = score < 40
```

### 13.4 Evaluation Test Cases (12 Total)

| ID | Agent | Question | Ground Truth SQL |
|----|-------|----------|-----------------|
| CRM-01 | CRM | How many total deals do we have? | `SELECT COUNT(*) FROM warehouse.fact_deals` |
| CRM-02 | CRM | What is the overall win rate? | `SELECT ROUND(COUNT(*) FILTER (WHERE status='won')*100.0 / NULLIF(COUNT(*),0), 1) FROM warehouse.fact_deals WHERE status IN ('won','lost')` |
| CRM-03 | CRM | How many companies do we have in the CRM? | `SELECT COUNT(*) FROM companies WHERE is_deleted = false` |
| CRM-04 | CRM | What is the total value of the active pipeline? | `SELECT COALESCE(SUM(value_tnd),0) FROM warehouse.fact_deals WHERE status='open'` |
| CRM-05 | CRM | How many deals are in the negotiation stage? | `SELECT COUNT(*) FROM warehouse.fact_deals WHERE stage='Negotiation'` |
| FIN-01 | Finance | What is the total collected revenue from paid invoices? | `SELECT COALESCE(SUM(total_amount),0) FROM warehouse.fact_revenue WHERE status='paid'` |
| FIN-02 | Finance | What is the collection rate? | `SELECT ROUND(COUNT(*) FILTER (WHERE status='paid')*100.0 / NULLIF(COUNT(*),0), 1) FROM warehouse.fact_revenue` |
| FIN-03 | Finance | How many invoices are overdue? | `SELECT COUNT(*) FROM warehouse.fact_revenue WHERE status='overdue'` |
| FIN-04 | Finance | What is the total pending invoice amount? | `SELECT COALESCE(SUM(total_amount),0) FROM warehouse.fact_revenue WHERE status='pending'` |
| FIN-05 | Finance | How many total invoices do we have? | `SELECT COUNT(*) FROM warehouse.fact_revenue` |
| DA-01 | Data Analyst | create a bar chart of deal count by stage from fact_deals | `SELECT stage, COUNT(*) FROM warehouse.fact_deals GROUP BY stage ORDER BY count DESC` |
| DA-02 | Data Analyst | create a pie chart of invoice status distribution from fact_revenue | `SELECT status, COUNT(*) FROM warehouse.fact_revenue GROUP BY status` |

### 13.5 Multi-Metric Evaluation Schema

Defined in `backend/migrations/update_evaluation_schema.sql`:

| Metric | Weight | Description |
|--------|--------|-------------|
| `task_adherence` | 0.25 | Did the agent complete exactly what the user requested |
| `tool_call_accuracy` | 0.20 | Correct tool called with correct parameters |
| `intent_resolution` | 0.20 | Did the agent correctly interpret user intent |
| `context_relevance` | 0.15 | RAG: relevance of retrieved context to query |
| `retrieval_precision` | 0.10 | RAG: fraction of retrieved chunks actually useful |
| `ndcg` | 0.04 | RAG: Normalized Discounted Cumulative Gain |
| `hit_rate` | 0.03 | RAG: binary — at least one relevant doc retrieved |
| `reciprocal_rank` | 0.03 | RAG: 1/rank of first relevant chunk |

When RAG metrics are NULL (RAG not used): weights rebalanced to sum to 1.0 across non-RAG metrics.

### 13.6 Shared Prompt Constants

**File**: `backend/agents/prompt_parts.py`

| Constant | Content Summary |
|----------|----------------|
| `TND_FORMAT_RULE` | "Always express monetary amounts in TND (Tunisian Dinars). Never use EUR, USD, or DZD." |
| `LANGUAGE_RULE` | "Respond in the same language the user used (French or English). Never mix." |
| `TOOL_CALL_ENFORCEMENT` | "You MUST call a tool for every factual query. Never invent data. LAST LINE OF PROMPT." |
| `RECORD_FORMAT` | Procedural format instructions (no filled-in examples — prevents pattern completion) |
| `OUTPUT_TAG_RULE` | "Begin every response with [CRM], [INVOICING], [CHART], or [GENERAL]" |
| `CONFIRMATION_SYSTEM` | Two-phase write system description: preview on confirmed=False, execute on confirmed=True |

---

## 14. Database Schemas

### 14.1 Operational Tables (public.*)

#### users
```sql
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR UNIQUE NOT NULL,
    email           VARCHAR UNIQUE,
    full_name       VARCHAR,
    hashed_password VARCHAR NOT NULL,
    role            VARCHAR DEFAULT 'user',    -- 'admin' | 'user'
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

#### companies
```sql
CREATE TABLE companies (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR NOT NULL,
    industry   VARCHAR,
    status     VARCHAR DEFAULT 'prospect',     -- prospect|active|inactive|churned
    phone      VARCHAR,
    email      VARCHAR,
    city       VARCHAR,
    country    VARCHAR DEFAULT 'Tunisia',
    is_deleted BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### contacts
```sql
CREATE TABLE contacts (
    id          SERIAL PRIMARY KEY,
    first_name  VARCHAR NOT NULL,
    last_name   VARCHAR NOT NULL,
    email       VARCHAR,
    phone       VARCHAR,
    role        VARCHAR,
    company_id  INTEGER REFERENCES companies(id),
    is_deleted  BOOLEAN DEFAULT false,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

#### deals
```sql
CREATE TABLE deals (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR NOT NULL,
    company_id  INTEGER REFERENCES companies(id),
    value       NUMERIC(14, 2),
    stage       VARCHAR DEFAULT 'Prospection',
    status      VARCHAR DEFAULT 'open',        -- open|won|lost
    probability NUMERIC(5, 2) DEFAULT 0,
    is_deleted  BOOLEAN DEFAULT false,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW(),
    closed_at   TIMESTAMP
);
```

#### activities
```sql
CREATE TABLE activities (
    id          SERIAL PRIMARY KEY,
    company_id  INTEGER REFERENCES companies(id),
    contact_id  INTEGER REFERENCES contacts(id),
    user_id     INTEGER REFERENCES users(id),
    type        VARCHAR,
    description TEXT,
    due_date    TIMESTAMP,
    done_at     TIMESTAMP,
    is_done     BOOLEAN DEFAULT false,
    is_deleted  BOOLEAN DEFAULT false,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

#### invoices
```sql
CREATE TABLE invoices (
    id             SERIAL PRIMARY KEY,
    invoice_number VARCHAR UNIQUE NOT NULL,    -- INV-YYYY-NNNN
    company_id     INTEGER REFERENCES companies(id),
    issue_date     DATE NOT NULL,
    due_date       DATE NOT NULL,
    subtotal       NUMERIC(14, 2) DEFAULT 0,
    tax_amount     NUMERIC(14, 2) DEFAULT 0,
    total          NUMERIC(14, 2) DEFAULT 0,
    status         VARCHAR DEFAULT 'draft',    -- draft|sent|paid|overdue|cancelled
    paid_at        TIMESTAMP,
    is_deleted     BOOLEAN DEFAULT false,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);
```

#### invoice_items
```sql
CREATE TABLE invoice_items (
    id           SERIAL PRIMARY KEY,
    invoice_id   INTEGER REFERENCES invoices(id),
    description  VARCHAR NOT NULL,
    quantity     NUMERIC(10, 2) DEFAULT 1,
    unit_price   NUMERIC(14, 2) NOT NULL,
    total        NUMERIC(14, 2) NOT NULL
);
```

#### sessions
```sql
CREATE TABLE sessions (
    id             SERIAL PRIMARY KEY,
    session_id     VARCHAR UNIQUE NOT NULL,
    history        TEXT,                        -- JSON: last 20 messages
    pending_action TEXT,                        -- Serialized write preview
    tool_calls     TEXT,                        -- JSON: [{tool, params}]
    rag_context    TEXT,                        -- Injected RAG context
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);
```

#### audit_log
```sql
CREATE TABLE audit_log (
    id         SERIAL PRIMARY KEY,
    action     VARCHAR NOT NULL,                -- create|update|delete|etc.
    entity     VARCHAR NOT NULL,                -- company|deal|invoice|etc.
    entity_id  INTEGER,
    payload    JSONB,                           -- Input parameters
    result     TEXT,                            -- Success/error message
    user_id    INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### axis_charts
```sql
CREATE TABLE axis_charts (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    chart_type  TEXT NOT NULL,
    data_source TEXT NOT NULL,
    chart_json  JSONB NOT NULL,                 -- Plotly figure dict
    created_at  TIMESTAMP DEFAULT NOW(),
    created_by  TEXT
);
```

#### axis_exchange_evaluations
```sql
CREATE TABLE axis_exchange_evaluations (
    id                  SERIAL PRIMARY KEY,
    session_id          VARCHAR,
    exchange_index      INTEGER,
    question            TEXT,
    answer              TEXT,
    -- Multi-metric columns (added via migration):
    context_relevance   NUMERIC(4,3),           -- RAG metric
    retrieval_precision NUMERIC(4,3),           -- RAG metric
    hit_rate            NUMERIC(4,3),           -- RAG metric
    reciprocal_rank     NUMERIC(4,3),           -- RAG metric
    ndcg                NUMERIC(4,3),           -- RAG metric
    task_adherence      NUMERIC(4,3),           -- Agent metric
    tool_call_accuracy  NUMERIC(4,3),           -- Agent metric
    intent_resolution   NUMERIC(4,3),           -- Agent metric
    overall_score       NUMERIC(4,3),           -- Weighted composite
    evaluation_notes    TEXT,                   -- Semicolon-separated judge notes
    created_at          TIMESTAMP DEFAULT NOW()
);

-- CHECK constraints: all metric columns must be in [0.0, 1.0] or NULL
```

### 14.2 Warehouse Schema (warehouse.*)

#### warehouse.dim_client
```sql
CREATE TABLE warehouse.dim_client (
    client_id    SERIAL PRIMARY KEY,
    company_name VARCHAR NOT NULL,
    phone        VARCHAR,
    email        VARCHAR,
    city         VARCHAR,
    country      VARCHAR,
    industry     VARCHAR,
    status       VARCHAR,
    created_date DATE,
    source_file  VARCHAR,
    loaded_at    TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.dim_employee
```sql
CREATE TABLE warehouse.dim_employee (
    employee_id   SERIAL PRIMARY KEY,
    username      VARCHAR,
    full_name     VARCHAR,
    role          VARCHAR,
    department    VARCHAR,
    hire_date     DATE,
    loaded_at     TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.dim_service
```sql
CREATE TABLE warehouse.dim_service (
    service_id   SERIAL PRIMARY KEY,
    service_name VARCHAR,
    category     VARCHAR,
    unit_price   NUMERIC(14, 2),
    loaded_at    TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.dim_date
```sql
CREATE TABLE warehouse.dim_date (
    date_key       DATE PRIMARY KEY,
    year           INTEGER,
    quarter        INTEGER,
    month          INTEGER,
    month_name     VARCHAR,
    week_of_year   INTEGER,
    day_of_week    INTEGER,
    day_name       VARCHAR,
    is_weekend     BOOLEAN,
    fiscal_year    INTEGER
);
```

#### warehouse.fact_deals
```sql
CREATE TABLE warehouse.fact_deals (
    deal_id           SERIAL PRIMARY KEY,
    deal_ref          VARCHAR,                  -- DEAL-000001
    company_name      VARCHAR NOT NULL,
    title             VARCHAR,
    stage             VARCHAR,
    status            VARCHAR,                  -- open|won|lost
    value_tnd         NUMERIC(14, 2),
    probability       NUMERIC(5, 2),
    deal_size_category VARCHAR,                 -- Small|Medium|Large|Enterprise
    quarter           VARCHAR,                  -- Q2 2024
    days_to_close     INTEGER,
    created_date      DATE,
    closed_date       DATE,
    assigned_to       VARCHAR,
    loaded_at         TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.fact_revenue
```sql
CREATE TABLE warehouse.fact_revenue (
    revenue_id          SERIAL PRIMARY KEY,
    invoice_number      VARCHAR,
    company_name        VARCHAR NOT NULL,
    invoice_date        DATE,
    due_date            DATE,
    subtotal            NUMERIC(14, 2),
    tax_amount          NUMERIC(14, 2),
    total_amount        NUMERIC(14, 2),
    amount_paid         NUMERIC(14, 2) DEFAULT 0,
    status              VARCHAR,                -- pending|paid|overdue|cancelled
    payment_delay_days  INTEGER,
    is_overdue          BOOLEAN DEFAULT false,
    days_outstanding    INTEGER DEFAULT 0,
    loaded_at           TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.fact_activities
```sql
CREATE TABLE warehouse.fact_activities (
    activity_id      SERIAL PRIMARY KEY,
    source_id        VARCHAR,                   -- ACT-0000001
    company_name     VARCHAR NOT NULL,
    contact_name     VARCHAR,
    activity_type    VARCHAR,                   -- Appel|Email|Réunion|Task|etc.
    activity_date    DATE,
    duration_min     INTEGER,
    outcome          VARCHAR,                   -- positive|negative|neutral
    churn_signal     BOOLEAN DEFAULT false,
    positive_signal  BOOLEAN DEFAULT false,
    description      TEXT,
    assigned_to      VARCHAR,
    deal_reference   VARCHAR,
    loaded_at        TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.fact_project_performance
```sql
CREATE TABLE warehouse.fact_project_performance (
    project_id         SERIAL PRIMARY KEY,
    project_name       VARCHAR,
    company_name       VARCHAR,
    status             VARCHAR,
    start_date         DATE,
    end_date           DATE,
    budget_tnd         NUMERIC(14, 2),
    actual_cost_tnd    NUMERIC(14, 2),
    completion_pct     NUMERIC(5, 2),
    assigned_to        VARCHAR,
    loaded_at          TIMESTAMP DEFAULT NOW()
);
```

#### warehouse.fact_hr_events
```sql
CREATE TABLE warehouse.fact_hr_events (
    event_id       SERIAL PRIMARY KEY,
    employee_name  VARCHAR,
    event_type     VARCHAR,                     -- hire|leave|promotion|etc.
    event_date     DATE,
    department     VARCHAR,
    notes          TEXT,
    loaded_at      TIMESTAMP DEFAULT NOW()
);
```

### 14.3 Context Variables (Per-Request State)

**File**: `backend/agents/context.py`

```python
from contextvars import ContextVar

_pending_action_var: ContextVar[str | None] = ContextVar('pending_action', default=None)
_rag_context_var:    ContextVar[str | None] = ContextVar('rag_context',    default=None)
_tool_calls_var:     ContextVar[list]       = ContextVar('tool_calls',     default=[])

# API:
def set_pending_action(value: str | None) -> None: ...
def get_pending_action() -> str | None: ...
def clear_pending_action() -> None: ...

def set_rag_context(value: str | None) -> None: ...
def get_rag_context() -> str | None: ...

def set_tool_calls(value: list) -> None: ...
def get_tool_calls() -> list: ...
def append_tool_call(tool: str, params: dict) -> None: ...
```

---

## 15. Configuration & Constants

### 15.1 .env File (Runtime Configuration)

```ini
# Ollama
OLLAMA_BASE_URL=http://localhost:11434

# Database
DATABASE_URL=postgresql://erp_user:erp_pass@localhost:5432/erp_db

# JWT (overrides code defaults)
SECRET_KEY=supersecretkey123
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60    # Note: code uses hours=8, .env wins

# Application
APP_ENV=development

# SMTP (Gmail for credential delivery)
SMTP_EMAIL=your-email@gmail.com
SMTP_APP_PASSWORD=your-app-password
```

### 15.2 Code-Level Constants

| Constant | Value | File | Purpose |
|----------|-------|------|---------|
| `ERP_MODEL` | `"qwen2.5:7b"` | `backend/agents/llm.py` | Single LLM for all agents |
| `DEFAULT_LIST_LIMIT` | `50` | `backend/tools/crm_tools.py` | Default records returned by list tools |
| `TVA` | `19.0` | `backend/tools/invoice_tools.py` | Tunisia VAT rate (%) |
| `EMBED_BATCH` | `25` | `backend/rag/embedding_pipeline.py` | Embedding batch size |
| `CHUNK_SIZE` | `500` | `backend/rag/embedding_pipeline.py` | Text chunk size (chars) |
| `CHUNK_OVERLAP` | `50` | `backend/rag/embedding_pipeline.py` | Chunk overlap (chars) |
| `SECRET_KEY` | `"axis-secret-key-jbm-consulting-2024"` | `backend/auth.py` | JWT signing key (code) |
| `ALGORITHM` | `"HS256"` | `backend/auth.py` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `8` | `backend/auth.py` | JWT expiry (code) |
| `PENDING_ACTION_TTL` | `300` | `backend/main.py` | Seconds before pending action expires |
| `SESSION_HISTORY_CAP` | `20` | `backend/main.py` | Max messages stored per session |
| `JUDGE_MODEL` | `"qwen2.5:7b"` | `backend/evaluation/evaluator.py` | LLM-as-Judge model |
| `PASS_THRESHOLD` | `70` | `backend/evaluation/evaluator.py` | Score ≥ 70 = PASS |
| `PARTIAL_THRESHOLD` | `40` | `backend/evaluation/evaluator.py` | Score 40–69 = PARTIAL |
| `CHURN_DEDUP_THRESHOLD` | `85` | `airflow/dags/etl_jbm_pipeline.py` | rapidfuzz similarity threshold |
| `ACTIVITY_CHUNK_SIZE` | `50_000` | `airflow/dags/etl_jbm_pipeline.py` | Activities ETL chunk |
| `hole` | `0.38` | `backend/tools/chart_tools.py` | Donut chart hole size |
| `VALID_CHART_TYPES` | `{'bar','line','scatter','pie','donut','funnel','area'}` | `backend/tools/chart_tools.py` | Allowed chart types |
| `VALID_DATA_SOURCES` | `{'fact_deals','fact_revenue','fact_activities','dim_client'}` | `backend/tools/chart_tools.py` | Allowed data sources |

### 15.3 Deal Size Thresholds (Used in ETL + rebuild_warehouse.sql)

```python
# Consistent across: etl_jbm_pipeline.py, rebuild_warehouse.sql
DEAL_SIZE_MAP = {
    "Small":      value < 5_000,
    "Medium":     5_000 <= value < 20_000,
    "Large":      20_000 <= value < 100_000,
    "Enterprise": value >= 100_000,
}
```

### 15.4 Quarter Format (Used in ETL + rebuild_warehouse.sql)

```python
# ETL Python
quarter = f"Q{(d.month-1)//3+1} {d.year}"     # e.g., "Q2 2024"

# SQL
quarter = 'Q' || EXTRACT(QUARTER FROM created_at)::int
          || ' ' || EXTRACT(YEAR FROM created_at)::int
```

### 15.5 Churn/Positive Signal Keywords (Used in ETL + rebuild_warehouse.sql)

All three locations must stay in sync:

**Churn signals (negative)**:
`insatisfait`, `concurrent`, `resilie/résilié`, `annule/annulé`, `probleme/problème`, `plainte`, `bloque/bloqué`, `pas satisfait`, `decu/déçu`, `qualite trop/qualité trop`, `tarif trop`

**Positive signals**:
`satisfait`, `excellent`, `renouvellement`, `recommande/recommandé`, `signe/signé`, `valide/validé`, `accord`, `ravi`, `confiant`, `upsell`, `croissance`, `partenariat`, `fidelite/fidélité`, `expansion`

### 15.6 Validation Thresholds (ETL Step 14)

```python
VALIDATION_THRESHOLDS = {
    "dim_client":      500,
    "fact_deals":    3_000,
    "fact_activities": 50_000,
    "fact_revenue":    500,
    "dim_date":      1_000,
}
WIN_RATE_BOUNDS = (10.0, 90.0)   # Acceptable win rate range (percent)
```

### 15.7 Normalization Character Set

```python
# Characters injected by generate_raw_data.py to create "dirty" names
POLLUTED_CHARS = "[*#!@]"   # Used in: cleanup_companies.sql, populate_operational.py

# Python normalization function
def _normalize_company_name(name: str) -> str:
    """Strip *#!@, collapse whitespace, lowercase — for dedup comparison only."""
    cleaned = re.sub(r'[*#!@]', '', name)
    return re.sub(r'\s+', ' ', cleaned).strip().lower()
```

### 15.8 Activity Type Normalization Map

| Raw value | Normalized value |
|-----------|----------------|
| `call`, `appel` | `Appel` |
| `email`, `courriel` | `Email` |
| `meeting`, `reunion`, `réunion` | `Réunion` |
| `task` | `Task` |
| `note` | `Note` |
| `demo`, `démo` | `Démo` |
| `visit`, `visite` | `Visite` |
| `follow-up`, `relance` | `Relance` |
| `support` | `Support` |
| `training`, `formation` | `Formation` |
| *(anything else)* | `INITCAP(type)` |

### 15.9 Invoice Status Values

| Status | Description |
|--------|-------------|
| `draft` | Created but not sent |
| `sent` | Delivered to client |
| `paid` | Payment received |
| `overdue` | Past due date, unpaid |
| `cancelled` | Voided |

### 15.10 Deal Stage Values (Standard Pipeline)

`Prospection` → `Qualification` → `Proposition` → `Négociation` → `Clôture`

(Also used: `Negotiation` in English queries — both forms exist in data)

### 15.11 Company Status Values

`prospect` | `active` | `inactive` | `churned`

### 15.12 Temperature Scaling Summary

| Model | Formula | Effect |
|-------|---------|--------|
| Churn | `0.5 + (prob - 0.5) * 0.75` | Slight compression toward 0.5 |
| Deal win | `0.5 + (prob - 0.5) * 0.55` | Stronger compression toward 0.5 |

Both applied after `CalibratedClassifierCV` Platt scaling.

### 15.13 Key Engineering Lessons (from tasks/lessons.md)

| Lesson | Rule |
|--------|------|
| No filled-in template examples in prompts | qwen2.5:7b pattern-completes without calling tools |
| `TOOL_CALL_ENFORCEMENT` must be last line | Small models have strong recency bias |
| RAG harmful for list queries | ~0.4 cosine noise → wrong company filter |
| List formatting belongs in interceptor | Fragile when in prompt, deterministic when in code |
| Short routing answers need conversational context | "BNA" after disambiguation inherits CRM via last-turn tag |
| Hard-kill server when changing agents/prompts | `--reload` does not reinitialize cached AgentExecutor instances |
| Normalization must be kept in sync across all sites | Drift silently reintroduces cleaned data |
| `python -c` multi-line fails on Windows | Use throwaway `.py` file + delete after |

---

*End of AXIS Complete Technical Documentation.*  
*All engineering decisions, bypasses, fallbacks, tools, agents, pipeline steps, and ML models documented.*
