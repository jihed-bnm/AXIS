"""
Embedding pipeline — reads from warehouse schema tables and stores
vector embeddings in ChromaDB (local persistent store at ./chroma_db).

Usage:
    python -m backend.rag.embedding_pipeline           # full run
    python -m backend.rag.embedding_pipeline --update  # incremental (last 24h)

Warehouse tables used (never operational schema):
    warehouse.fact_activities   ~200,000 rows  -> jbm_crm collection
    warehouse.fact_deals           ~8,000 rows  -> jbm_crm collection
    warehouse.dim_client          ~16,547 rows  -> jbm_crm collection
    warehouse.fact_revenue         ~2,376 rows  -> jbm_invoicing collection

Currency: always TND.
"""
import sys
import time
from typing import Any, List

import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sqlalchemy import text

from backend.models.database import engine

# ── ChromaDB client and collections ───────────────────────────────────────────

chroma_client = chromadb.PersistentClient(path="./chroma_db")

crm_collection = chroma_client.get_or_create_collection(
    name="jbm_crm",
    metadata={"hnsw:space": "cosine"},
)

invoicing_collection = chroma_client.get_or_create_collection(
    name="jbm_invoicing",
    metadata={"hnsw:space": "cosine"},
)

# ── Embedding model ────────────────────────────────────────────────────────────

embeddings_model = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://localhost:11434",
)

# ── Text splitter ──────────────────────────────────────────────────────────────

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", ". ", " ", ""],
)

EMBED_BATCH = 25
PROGRESS_INTERVAL = 1000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _embed_and_store(collection, records: List[dict]) -> int:
    """
    Split each record into chunks, embed and store each batch of 25 immediately.
    Prints progress with estimated time remaining. Returns total chunks stored.
    """
    pending_texts: List[str] = []
    pending_meta: List[tuple] = []   # (id, metadata)
    total_chunks = 0
    total_records = len(records)
    start_time = time.time()

    def _flush_batch():
        nonlocal total_chunks
        if not pending_texts:
            return
        batch_texts = pending_texts[:EMBED_BATCH]
        batch_meta = pending_meta[:EMBED_BATCH]
        del pending_texts[:EMBED_BATCH]
        del pending_meta[:EMBED_BATCH]

        try:
            vectors = embeddings_model.embed_documents(batch_texts)
        except Exception:
            time.sleep(2)
            vectors = embeddings_model.embed_documents(batch_texts)

        collection.add(
            ids=[m[0] for m in batch_meta],
            embeddings=vectors,
            documents=batch_texts,
            metadatas=[m[1] for m in batch_meta],
        )
        total_chunks += len(batch_texts)

        if total_chunks % PROGRESS_INTERVAL == 0 or total_chunks <= EMBED_BATCH:
            elapsed = time.time() - start_time
            rate = total_chunks / elapsed if elapsed > 0 else 0
            remaining = (total_records - total_chunks) / rate if rate > 0 else 0
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            eta = f"~{mins} min {secs} sec remaining" if mins > 0 else f"~{secs} sec remaining"
            print(f"    Embedded {total_chunks:,}/{total_records:,} | {eta}")

    for rec in records:
        chunks = splitter.split_text(rec["content"])
        base_id = rec["base_id"]
        meta = rec["metadata"]

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{base_id}__{idx}"
            pending_texts.append(chunk)
            pending_meta.append((chunk_id, meta))

            if len(pending_texts) >= EMBED_BATCH:
                _flush_batch()

    # Flush remaining
    while pending_texts:
        _flush_batch()

    return total_chunks


# ── Source: warehouse.fact_activities ─────────────────────────────────────────

def embed_activities(incremental: bool = False) -> int:
    time_filter = "AND loaded_at > NOW() - INTERVAL '24 hours'" if incremental else ""

    # Count unfiltered total to report reduction clearly
    count_query = text("""
        SELECT COUNT(*) FROM warehouse.fact_activities
    """)
    with engine.connect() as conn:
        total_before = conn.execute(count_query).scalar()

    query = text(f"""
        SELECT source_id, company_name, activity_type, activity_date,
               outcome, description, churn_signal, positive_signal
        FROM warehouse.fact_activities
        WHERE description IS NOT NULL
          AND LENGTH(description) > 50
          AND description NOT LIKE '%Activité liée à%'
          AND description NOT LIKE 'TODO%'
          AND description NOT LIKE 'a remplir%'
          {time_filter}
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    print(f"  Filtered to {len(rows):,} meaningful activity records (from {total_before:,} total)")
    records = []
    for i, row in enumerate(rows):
        content = (
            f"Activity: {_safe_str(row.activity_type)}\n"
            f"Company: {_safe_str(row.company_name)}\n"
            f"Date: {_safe_str(row.activity_date)}\n"
            f"Outcome: {_safe_str(row.outcome)}\n"
            f"Description: {_safe_str(row.description)}"
        )
        metadata = {
            "source": "activity",
            "activity_id": _safe_str(row.source_id),
            "company_name": _safe_str(row.company_name),
            "activity_type": _safe_str(row.activity_type),
            "outcome": _safe_str(row.outcome),
            "churn_signal": str(bool(row.churn_signal)),
            "positive_signal": str(bool(row.positive_signal)),
        }
        records.append({
            "content": content,
            "metadata": metadata,
            "base_id": f"activity__{i}",  # row index guarantees uniqueness
        })

    return _embed_and_store(crm_collection, records)


# ── Source: warehouse.fact_deals ──────────────────────────────────────────────

def embed_deals(incremental: bool = False) -> int:
    time_filter = "AND loaded_at > NOW() - INTERVAL '24 hours'" if incremental else ""

    count_query = text(f"""
        SELECT COUNT(*) FROM warehouse.fact_deals
        WHERE title IS NOT NULL
          {time_filter}
    """)
    with engine.connect() as conn:
        total_before = conn.execute(count_query).scalar()

    query = text(f"""
        SELECT deal_id, deal_ref, company_name, title, stage,
               status, value_tnd, assigned_to, created_date, closed_date
        FROM warehouse.fact_deals
        WHERE title IS NOT NULL
          AND LENGTH(title) > 30
          {time_filter}
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    print(f"  Filtered to {len(rows):,} meaningful deal records (from {total_before:,} total)")
    records = []
    for i, row in enumerate(rows):
        value_str = f"{float(row.value_tnd):,.2f} TND" if row.value_tnd is not None else "N/A TND"
        content = (
            f"Deal: {_safe_str(row.title)}\n"
            f"Company: {_safe_str(row.company_name)}\n"
            f"Value: {value_str}\n"
            f"Status: {_safe_str(row.status)}\n"
            f"Stage: {_safe_str(row.stage)}\n"
            f"Assigned to: {_safe_str(row.assigned_to)}\n"
            f"Created: {_safe_str(row.created_date)}"
        )
        metadata = {
            "source": "deal",
            "deal_ref": _safe_str(row.deal_ref),
            "company_name": _safe_str(row.company_name),
            "status": _safe_str(row.status),
            "value_tnd": str(float(row.value_tnd)) if row.value_tnd is not None else "",
        }
        records.append({
            "content": content,
            "metadata": metadata,
            "base_id": f"deal__{i}",
        })

    return _embed_and_store(crm_collection, records)


# ── Source: warehouse.dim_client ──────────────────────────────────────────────

def embed_clients(incremental: bool = False) -> int:
    time_filter = "AND loaded_at > NOW() - INTERVAL '24 hours'" if incremental else ""

    count_query = text(f"""
        SELECT COUNT(DISTINCT company_name) FROM warehouse.dim_client
        WHERE company_name IS NOT NULL
          {time_filter}
    """)
    with engine.connect() as conn:
        total_before = conn.execute(count_query).scalar()

    query = text(f"""
        SELECT DISTINCT ON (company_name)
            client_id, company_name, industry, city, country, status
        FROM warehouse.dim_client
        WHERE company_name IS NOT NULL
          {time_filter}
        ORDER BY company_name, client_id
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    print(f"  Filtered to {len(rows):,} canonical company records (from {total_before:,} unique names)")
    records = []
    for i, row in enumerate(rows):
        content = (
            f"Company: {_safe_str(row.company_name)}\n"
            f"Industry: {_safe_str(row.industry)}\n"
            f"City: {_safe_str(row.city)}\n"
            f"Country: {_safe_str(row.country)}\n"
            f"Status: {_safe_str(row.status)}"
        )
        metadata = {
            "source": "company",
            "company_name": _safe_str(row.company_name),
            "industry": _safe_str(row.industry),
            "status": _safe_str(row.status),
        }
        records.append({
            "content": content,
            "metadata": metadata,
            "base_id": f"client__{i}",
        })

    return _embed_and_store(crm_collection, records)


# ── Source: warehouse.fact_revenue ────────────────────────────────────────────

def embed_invoices(incremental: bool = False) -> int:
    time_filter = "AND loaded_at > NOW() - INTERVAL '24 hours'" if incremental else ""
    query = text(f"""
        SELECT revenue_id, invoice_number, company_name,
               invoice_date, due_date, total_amount, amount_paid,
               status, is_overdue
        FROM warehouse.fact_revenue
        WHERE invoice_number IS NOT NULL
          {time_filter}
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    print(f"  Invoices to embed: {len(rows):,}")
    records = []
    for i, row in enumerate(rows):
        total_str = f"{float(row.total_amount):,.2f} TND" if row.total_amount is not None else "N/A TND"
        paid_str = f"{float(row.amount_paid):,.2f} TND" if row.amount_paid is not None else "0.00 TND"
        content = (
            f"Invoice: {_safe_str(row.invoice_number)}\n"
            f"Company: {_safe_str(row.company_name)}\n"
            f"Amount: {total_str}\n"
            f"Paid: {paid_str}\n"
            f"Status: {_safe_str(row.status)}\n"
            f"Invoice date: {_safe_str(row.invoice_date)}\n"
            f"Due date: {_safe_str(row.due_date)}\n"
            f"Overdue: {bool(row.is_overdue)}"
        )
        metadata = {
            "source": "invoice",
            "invoice_number": _safe_str(row.invoice_number),
            "company_name": _safe_str(row.company_name),
            "status": _safe_str(row.status),
            "amount_tnd": str(float(row.total_amount)) if row.total_amount is not None else "",
        }
        records.append({
            "content": content,
            "metadata": metadata,
            "base_id": f"invoice__{i}",
        })

    return _embed_and_store(invoicing_collection, records)


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_full_pipeline():
    print("Starting full embedding pipeline...")
    print("Clearing existing ChromaDB collections...")
    chroma_client.delete_collection("jbm_crm")
    chroma_client.delete_collection("jbm_invoicing")

    # Re-create after deletion
    global crm_collection, invoicing_collection
    crm_collection = chroma_client.get_or_create_collection(
        name="jbm_crm", metadata={"hnsw:space": "cosine"}
    )
    invoicing_collection = chroma_client.get_or_create_collection(
        name="jbm_invoicing", metadata={"hnsw:space": "cosine"}
    )

    print("\n[1/4] Embedding activities (warehouse.fact_activities)...")
    n_activities = embed_activities()
    print(f"  Activities embedded: {n_activities:,} chunks")

    print("\n[2/4] Embedding deals (warehouse.fact_deals)...")
    n_deals = embed_deals()
    print(f"  Deals embedded: {n_deals:,} chunks")

    print("\n[3/4] Embedding companies (warehouse.dim_client)...")
    n_clients = embed_clients()
    print(f"  Companies embedded: {n_clients:,} chunks")

    print("\n[4/4] Embedding invoices (warehouse.fact_revenue)...")
    n_invoices = embed_invoices()
    print(f"  Invoices embedded: {n_invoices:,} chunks")

    print("\n" + "=" * 50)
    print("Embedding pipeline complete.")
    print(f"  CRM collection      : {crm_collection.count():,} documents")
    print(f"  Invoicing collection: {invoicing_collection.count():,} documents")
    print("=" * 50)


# ── Incremental update ─────────────────────────────────────────────────────────

def run_incremental_update():
    """
    Embeds only records loaded into the warehouse in the last 24 hours.
    Adds to existing collections without clearing them.
    """
    print("Starting incremental embedding update (last 24 hours)...")

    print("\n[1/4] Incremental activities...")
    n_activities = embed_activities(incremental=True)

    print("\n[2/4] Incremental deals...")
    n_deals = embed_deals(incremental=True)

    print("\n[3/4] Incremental companies...")
    n_clients = embed_clients(incremental=True)

    print("\n[4/4] Incremental invoices...")
    n_invoices = embed_invoices(incremental=True)

    total = n_activities + n_deals + n_clients + n_invoices
    print(f"\nIncremental update complete. {total:,} new chunks added.")


if __name__ == "__main__":
    if "--update" in sys.argv:
        run_incremental_update()
    else:
        run_full_pipeline()
