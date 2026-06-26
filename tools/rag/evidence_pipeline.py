"""Normalize evidence sources, chunks, and retrieval indexes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from collections.abc import Sequence

from schemas.sources import EvidenceChunk, Source
from tools.rag.chunking import fixed_overlap_chunks
from tools.rag.hybrid_retriever import HybridRetriever


@dataclass(frozen=True)
class RawEvidence:
    """Text plus source metadata before normalization."""

    source_type: str
    title: str
    text: str
    url: str | None = None
    summary: str = ""
    relevance_score: float = 0.0
    citation_key: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class EvidencePipelineResult:
    """Normalized sources, chunks, and a ready retriever."""

    sources: list[Source]
    chunks: list[EvidenceChunk]
    retriever: HybridRetriever


class EvidencePipeline:
    """Build Source, EvidenceChunk, and retriever records from raw evidence."""

    MAX_RAW_TEXT_CHARS = 30_000
    MAX_SUMMARY_CHARS = 900

    def __init__(
        self,
        job_id: str,
        *,
        retriever: HybridRetriever | None = None,
        chunk_size: int = 1_000,
        overlap: int = 150,
    ) -> None:
        self.job_id = job_id
        self.retriever = retriever or HybridRetriever(job_id=job_id)
        self.chunk_size = chunk_size
        self.overlap = overlap

    def ingest(self, items: Sequence[RawEvidence]) -> EvidencePipelineResult:
        """Return normalized source records, evidence chunks, and an indexed retriever."""
        self.retriever.reset()
        type_counts: defaultdict[str, int] = defaultdict(int)
        source_records: list[tuple[Source, str]] = []

        for item in items:
            source_type = self._normalize_source_type(item.source_type)
            type_counts[source_type] += 1
            source_records.append(
                (self._source_from_item(item, source_type, type_counts[source_type]), source_type)
            )

        chunks: list[EvidenceChunk] = []
        for source, source_type in source_records:
            source_chunks = self._chunks_for_source(source)
            chunks.extend(source_chunks)
            self.retriever.add_documents(
                [chunk.text for chunk in source_chunks],
                source_id=source.id,
                source_type=source_type,
                document_ids=[chunk.id for chunk in source_chunks],
            )

        return EvidencePipelineResult(
            sources=[source for source, _source_type in source_records],
            chunks=chunks,
            retriever=self.retriever,
        )

    def _source_from_item(self, item: RawEvidence, source_type: str, index: int) -> Source:
        text = self._normalize_text(item.text)
        return Source(
            id=item.source_id or f"{self.job_id}-{source_type}-source-{index}",
            job_id=self.job_id,
            title=item.title.strip() or "Untitled source",
            url=item.url,
            summary=item.summary.strip() or self._summary(text),
            relevance_score=item.relevance_score,
            raw_text=text[: self.MAX_RAW_TEXT_CHARS],
            citation_key=item.citation_key or self._citation_key(source_type, index),
        )

    def _chunks_for_source(self, source: Source) -> list[EvidenceChunk]:
        documents = fixed_overlap_chunks(
            source.raw_text,
            chunk_size=self.chunk_size,
            overlap=self.overlap,
        )
        return [
            EvidenceChunk(
                id=f"{source.id}-chunk-{index}",
                job_id=self.job_id,
                source_id=source.id,
                text=document,
                chunk_index=index,
                relevance_score=source.relevance_score,
            )
            for index, document in enumerate(documents)
        ]

    @classmethod
    def _summary(cls, text: str) -> str:
        return cls._normalize_text(text[: cls.MAX_SUMMARY_CHARS])

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_source_type(source_type: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", source_type.lower()).strip("-")
        return normalized or "unknown"

    @classmethod
    def _citation_key(cls, source_type: str, index: int) -> str:
        label = {
            "web": "Web",
            "upload": "Upload",
        }.get(source_type, source_type.title().replace("-", ""))
        return f"[{label or 'Source'}{index}]"
