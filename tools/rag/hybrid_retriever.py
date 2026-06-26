"""Hybrid vector + BM25 retriever."""

from dataclasses import dataclass

from tools.rag.bm25_store import BM25Store
from tools.rag.reranker import rerank
from tools.rag.vector_store import InMemoryVectorStore


@dataclass(frozen=True)
class RetrievalResult:
    """A scored hybrid retrieval result."""

    id: str
    text: str
    source_id: str
    source_type: str
    fused_score: float
    rerank_score: float


class HybridRetriever:
    """Combine vector and keyword retrieval before reranking."""

    def __init__(
        self,
        vector_store: InMemoryVectorStore | None = None,
        bm25_store: BM25Store | None = None,
        *,
        job_id: str = "default",
    ) -> None:
        """Initialize retriever with stores."""
        self.job_id = job_id
        self.vector_store = vector_store or InMemoryVectorStore(job_id)
        self.bm25_store = bm25_store or BM25Store()

    def add_documents(
        self,
        documents: list[str],
        *,
        source_id: str,
        source_type: str = "unknown",
        document_ids: list[str] | None = None,
    ) -> None:
        """Add documents to both vector and BM25 indexes."""
        if document_ids is not None and len(document_ids) != len(documents):
            raise ValueError("document_ids must match documents length")

        for index, document in enumerate(documents):
            record_id = (
                document_ids[index]
                if document_ids is not None
                else f"{self.job_id}-{source_id}-{index}"
            )
            self.vector_store.add_text(record_id, document, source_id, source_type)
            self.bm25_store.add_text(record_id, document, source_id, source_type)

    def retrieve(
        self,
        query: str,
        filters: dict[str, str] | None = None,
        *,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        """Return top hybrid results after score fusion and reranking."""
        filters = filters or {}
        vector_hits = self._filter_hits(self.vector_store.search(query, limit=20), filters)
        bm25_hits = self._filter_hits(self.bm25_store.search(query, limit=20), filters)
        vector_scores = {record.id: score for record, score in vector_hits}
        bm25_scores = {record.id: score for record, score in bm25_hits}
        records = {record.id: record for record, _score in vector_hits + bm25_hits}
        vector_norm = self._normalize_scores(vector_scores)
        bm25_norm = self._normalize_scores(bm25_scores)
        fused: list[tuple[str, float]] = []
        for record_id in records:
            score = (0.6 * vector_norm.get(record_id, 0.0)) + (0.4 * bm25_norm.get(record_id, 0.0))
            fused.append((record_id, score))
        top_fused = sorted(fused, key=lambda item: item[1], reverse=True)[:40]
        text_by_id = {record_id: records[record_id].text for record_id, _score in top_fused}
        reranked = rerank(query, list(text_by_id.values()), limit=min(40, len(text_by_id)))
        rerank_by_text = {text: score for text, score in reranked}
        final = sorted(
            top_fused,
            key=lambda item: (rerank_by_text.get(text_by_id[item[0]], 0.0), item[1]),
            reverse=True,
        )[:limit]
        return [
            RetrievalResult(
                id=record_id,
                text=records[record_id].text,
                source_id=records[record_id].source_id,
                source_type=records[record_id].source_type,
                fused_score=fused_score,
                rerank_score=rerank_by_text.get(records[record_id].text, 0.0),
            )
            for record_id, fused_score in final
        ]

    def search(self, query: str, *, limit: int = 5) -> list[str]:
        """Return reranked evidence snippets for backward compatibility."""
        return [result.text for result in self.retrieve(query, limit=limit)]

    def reset(self) -> None:
        """Clear per-job retrieval state."""
        self.vector_store.records.clear()
        self.bm25_store.records.clear()

    @staticmethod
    def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
        """Normalize scores to a 0-1 range."""
        if not scores:
            return {}
        min_score = min(scores.values())
        max_score = max(scores.values())
        if max_score == min_score:
            return {key: 1.0 for key in scores}
        return {key: (value - min_score) / (max_score - min_score) for key, value in scores.items()}

    @staticmethod
    def _filter_hits(
        hits: list[tuple[object, float]],
        filters: dict[str, str],
    ) -> list[tuple[object, float]]:
        """Apply metadata filters to vector or BM25 hits."""
        source_type = filters.get("source_type")
        if source_type is None:
            return hits
        return [
            (record, score)
            for record, score in hits
            if getattr(record, "source_type", "unknown") == source_type
        ]
