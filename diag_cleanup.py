"""
Step 1: Soft-delete 5 pollution records.
Step 2: Verify they don't surface in list_companies / list_contacts tool output
        or via RAG retrieval.
Run with: python diag_cleanup.py
Delete after use.
"""
from backend.models.database import get_session
from sqlalchemy import text
from backend.tools.crm_tools import list_companies, list_contacts

db = get_session()

# ─── Step 1: Soft-delete ──────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1 — Soft-delete 5 pollution records")
print("=" * 70)

db.execute(text(
    "UPDATE companies SET is_deleted=true WHERE id IN (905, 906)"
))
db.execute(text(
    "UPDATE contacts SET is_deleted=true WHERE id IN (4118, 4119, 4120)"
))
db.commit()
print("  Soft-deleted companies 905, 906 and contacts 4118, 4119, 4120.")

# Verify
r1 = db.execute(text(
    "SELECT id, name, is_deleted FROM companies WHERE id IN (905, 906)"
)).fetchall()
r2 = db.execute(text(
    "SELECT id, first_name, last_name, is_deleted FROM contacts WHERE id IN (4118, 4119, 4120)"
)).fetchall()
print(f"  Companies after update: {r1}")
print(f"  Contacts after update:  {r2}")
db.close()

# ─── Step 2a: Tool-layer check ─────────────────────────────────────────────────
print()
print("=" * 70)
print("STEP 2a — Tool-layer: list_companies and list_contacts")
print("=" * 70)

companies_output = list_companies.invoke({})
contacts_output  = list_contacts.invoke({})

test_strings = ["Test Solutions", "TestCorpDelete", "Ahmed Test", "Test User"]
print("\nlist_companies output (first 600 chars):")
print(companies_output[:600])
print()
for s in test_strings:
    present = s.lower() in companies_output.lower() or s.lower() in contacts_output.lower()
    print(f"  '{s}' present in tool output: {present}")

print()
print("list_contacts output (first 400 chars):")
print(contacts_output[:400])

# ─── Step 2b: RAG-layer check ─────────────────────────────────────────────────
print()
print("=" * 70)
print("STEP 2b — RAG-layer: ChromaDB retrieval for pollution strings")
print("=" * 70)

try:
    import chromadb
    from langchain_ollama import OllamaEmbeddings

    chroma = chromadb.PersistentClient(path="./chroma_db")
    embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url="http://localhost:11434")

    crm_col = chroma.get_or_create_collection("jbm_crm",     metadata={"hnsw:space": "cosine"})
    inv_col = chroma.get_or_create_collection("jbm_invoicing", metadata={"hnsw:space": "cosine"})

    # Query both collections with each pollution string as a semantic query
    # AND do a full text scan of all docs
    pollution_hits = []
    for col_name, col in [("jbm_crm", crm_col), ("jbm_invoicing", inv_col)]:
        if col.count() == 0:
            continue
        result = col.get(limit=2000, include=["documents", "metadatas"])
        docs  = result.get("documents") or []
        metas = result.get("metadatas") or []
        ids   = result.get("ids") or []
        for i, doc in enumerate(docs):
            if not doc:
                continue
            for s in ["test solutions", "testcorpdelete", "ahmed test", "test user"]:
                if s in doc.lower():
                    pollution_hits.append({
                        "collection": col_name,
                        "chroma_id":  ids[i],
                        "meta":       metas[i],
                        "snippet":    doc[:200],
                    })

    if pollution_hits:
        print(f"  WARNING: {len(pollution_hits)} ChromaDB doc(s) still reference soft-deleted records:")
        for h in pollution_hits:
            print(f"    [{h['collection']}] id={h['chroma_id']} | meta={h['meta']}")
            print(f"    snippet: {h['snippet'][:120]}")
        print()
        print("  GATE FAILED — soft-deletes do NOT propagate to RAG.")
        print("  Stop here and report; do not proceed with fix pass.")
    else:
        print("  All collections scanned. Zero hits for any of the 5 soft-deleted records.")
        print("  GATE PASSED — soft-deletes are not surfaced by RAG.")

except Exception as e:
    print(f"  ChromaDB scan error: {e}")

print()
print("=" * 70)
print("DONE")
print("=" * 70)
