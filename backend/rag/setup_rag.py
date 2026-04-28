"""
One-time RAG setup script. Run this before using the chat interface.

Steps:
    1. Verify Ollama nomic-embed-text is reachable
    2. Run the full embedding pipeline (writes to ./chroma_db)
    3. Run a test query to confirm retrieval works

Usage:
    python -m backend.rag.setup_rag
"""
import sys
import urllib.request
import urllib.error
import json

from backend.rag.embedding_pipeline import run_full_pipeline
from backend.rag.retriever import ERPRetriever


def check_ollama() -> bool:
    """Return True if nomic-embed-text is available via Ollama."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            available = any("nomic-embed-text" in m for m in models)
            if available:
                print("nomic-embed-text model found in Ollama")
            else:
                print("WARNING: nomic-embed-text not found in Ollama.")
                print("  Pull it with: ollama pull nomic-embed-text")
                print(f"  Available models: {models}")
            return available
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Ollama at http://localhost:11434 — {e}")
        print("  Start Ollama with: ollama serve")
        return False


def run_test_query() -> bool:
    """Return True if at least one document is retrieved for a sample query."""
    print("\nRunning test retrieval query...")
    try:
        r = ERPRetriever(top_k=3)
        docs = r.retrieve("client meeting")
        if not docs:
            print("WARNING: Test query returned no results.")
            return False
        print(f"Test retrieval passed. Retrieved {len(docs)} document(s).")
        print(f"Sample: {docs[0].page_content[:200]}")
        return True
    except Exception as e:
        print(f"ERROR during test query: {e}")
        return False


def main():
    print("=" * 55)
    print("  JBM ERP — RAG Setup (ChromaDB)")
    print("=" * 55)

    print("\n[1/2] Checking Ollama availability...")
    if not check_ollama():
        print("\nSetup aborted: nomic-embed-text must be available before embedding.")
        sys.exit(1)

    print("\n[2/2] Running full embedding pipeline...")
    run_full_pipeline()

    ok = run_test_query()

    print("\n" + "=" * 55)
    if ok:
        print("  RAG system setup complete and working correctly.")
        print("  Vector store: ./chroma_db")
    else:
        print("  Setup finished but test query returned no results.")
        print("  Check that the ETL pipeline has been run first.")
    print("=" * 55)


if __name__ == "__main__":
    main()
