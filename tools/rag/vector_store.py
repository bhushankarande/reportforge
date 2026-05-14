"""Per-job vector store abstraction with in-memory fallback."""

from dataclasses import dataclass

from tools.rag.embeddings import cosine_similarity, embed_text


@dataclass
class VectorRecord:
    """Stored vector record."""

    id: str
    text: str
    embedding: list[float]
    source_id: str
    source_type: str = "unknown"


class InMemoryVectorStore:
    """Simple per-job vector store compatible with Chroma-style operations."""

    def __init__(self, job_id: str) -> None:
        """Initialize the per-job collection."""
        self.job_id = job_id
        self.collection_name = f"report_{job_id}"
        self.records: list[VectorRecord] = []

    def add_text(self, record_id: str, text: str, source_id: str, source_type: str = "unknown") -> None:
        """Add text to the collection."""
        self.records.append(VectorRecord(record_id, text, embed_text(text), source_id, source_type))

    def search(self, query: str, *, limit: int = 5) -> list[tuple[VectorRecord, float]]:
        """Search records by vector similarity."""
        query_embedding = embed_text(query)
        scored = [
            (record, cosine_similarity(query_embedding, record.embedding)) for record in self.records
        ]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
