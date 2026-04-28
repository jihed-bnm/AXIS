"""
ERPRetriever — semantic search over ChromaDB collections.

Collections:
    jbm_crm       — activities, deals, companies  (module="crm")
    jbm_invoicing — invoices                      (module="invoicing")

Usage:
    from backend.rag.retriever import ERPRetriever

    r = ERPRetriever(module="crm", top_k=5)
    docs = r.retrieve("Tunisie Telecom contract renewal")
    context = r.format_context(docs)
"""
from typing import List, Optional

import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain.schema import Document


class ERPRetriever:
    def __init__(self, module: str = "all", top_k: int = 5):
        self.module = module
        self.top_k = top_k
        self.embeddings = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )
        self.client = chromadb.PersistentClient(path="./chroma_db")

        if module == "crm":
            self.collections = [
                self.client.get_or_create_collection(
                    "jbm_crm", metadata={"hnsw:space": "cosine"}
                )
            ]
        elif module == "invoicing":
            self.collections = [
                self.client.get_or_create_collection(
                    "jbm_invoicing", metadata={"hnsw:space": "cosine"}
                )
            ]
        else:
            self.collections = [
                self.client.get_or_create_collection(
                    "jbm_crm", metadata={"hnsw:space": "cosine"}
                ),
                self.client.get_or_create_collection(
                    "jbm_invoicing", metadata={"hnsw:space": "cosine"}
                ),
            ]

    def retrieve(self, query: str, company_name: Optional[str] = None) -> List[Document]:
        query_embedding = self.embeddings.embed_query(query)

        where = (
            {"company_name": {"$eq": company_name}} if company_name else None
        )

        all_results: List[Document] = []
        for collection in self.collections:
            # Skip empty collections — ChromaDB raises if n_results > count
            if collection.count() == 0:
                continue

            n = min(self.top_k, collection.count())
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n,
                where=where,
            )

            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i]
                distance = results["distances"][0][i]
                similarity = 1 - distance
                all_results.append(
                    Document(
                        page_content=doc,
                        metadata={**metadata, "similarity": similarity},
                    )
                )

        all_results.sort(
            key=lambda x: x.metadata.get("similarity", 0), reverse=True
        )
        return all_results[: self.top_k]

    def retrieve_for_company(self, company_name: str, query: str) -> List[Document]:
        return self.retrieve(query, company_name=company_name)

    def format_context(self, docs: List[Document]) -> str:
        if not docs:
            return "No relevant context found."
        parts = []
        for i, doc in enumerate(docs, 1):
            sim = doc.metadata.get("similarity", 0)
            src = doc.metadata.get("source", "unknown")
            parts.append(
                f"[Context {i} - {src} (relevance: {sim:.2f})]:\n"
                f"{doc.page_content}"
            )
        return "\n\n".join(parts)
