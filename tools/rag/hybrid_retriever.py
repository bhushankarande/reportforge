"""Hybrid vector + BM25 retriever."""

from tools.rag.bm25_store import BM25Store
from tools.rag.reranker import rerank
from tools.rag.vector_store import InMemoryVectorStore


class HybridRetriever:
    """Combine vector and keyword retrieval before reranking."""

    def __init__(self, vector_store: InMemoryVectorStore, bm25_store: BM25Store) -> None:
        """Initialize retriever with stores."""
        self.vector_store = vector_store
        self.bm25_store = bm25_store

    def search(self, query: str, *, limit: int = 5) -> list[str]:
        """Return reranked evidence snippets."""
        vector_hits = [record.text for record, _score in self.vector_store.search(query, limit=limit)]
        bm25_hits = [record.text for record, _score in self.bm25_store.search(query, limit=limit)]
        deduped = list(dict.fromkeys(vector_hits + bm25_hits))
        return [document for document, _score in rerank(query, deduped, limit=limit)]
