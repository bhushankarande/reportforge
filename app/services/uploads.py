"""Uploaded document ingestion for the API layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from agents.document_reader_agent import DocumentReaderAgent
from schemas.sources import Source
from tools.storage import StorageManager


@dataclass(frozen=True)
class UploadDocument:
    """One uploaded file payload."""

    filename: str
    content: bytes


@dataclass(frozen=True)
class UploadIngestResult:
    """Normalized upload evidence returned to API callers."""

    files: list[str]
    source_ids: list[str]
    sources: list[Source]
    chunks_indexed: int


class UploadService:
    """Persist uploaded files and normalize them into evidence sources."""

    MAX_FILE_BYTES = 5_000_000

    def __init__(
        self,
        *,
        storage: StorageManager | None = None,
        reader: DocumentReaderAgent | None = None,
    ) -> None:
        self.storage = storage or StorageManager()
        self.reader = reader or DocumentReaderAgent()

    def ingest(
        self,
        *,
        job_id: str,
        documents: list[UploadDocument],
        existing_sources: list[Source],
    ) -> UploadIngestResult:
        """Save uploaded files and return normalized upload evidence."""
        if not documents:
            raise ValueError("at least one file is required")

        upload_dir = self.storage.job_dir(job_id, "uploads")
        paths: list[Path] = []
        try:
            for document in documents:
                paths.append(self._save_document(upload_dir, document))

            evidence = self.reader.read_evidence(job_id, [str(path) for path in paths])
        except Exception:
            self._cleanup(paths)
            raise

        sources = self._renumber_upload_sources(
            job_id=job_id,
            sources=evidence.sources,
            existing_sources=existing_sources,
        )
        return UploadIngestResult(
            files=[path.name for path in paths],
            source_ids=[source.id for source in sources],
            sources=sources,
            chunks_indexed=len(evidence.chunks),
        )

    def _save_document(self, upload_dir: Path, document: UploadDocument) -> Path:
        filename = self._safe_filename(document.filename)
        if not document.content:
            raise ValueError(f"uploaded file is empty: {filename}")
        if len(document.content) > self.MAX_FILE_BYTES:
            raise ValueError(f"uploaded file is too large: {filename}")

        path = self._unique_path(upload_dir, filename)
        path.write_bytes(document.content)
        return path

    @staticmethod
    def _safe_filename(filename: str) -> str:
        raw = Path(filename or "upload.txt").name.strip()
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
        if not safe:
            raise ValueError("uploaded file name is invalid")
        return safe[:160]

    @staticmethod
    def _unique_path(upload_dir: Path, filename: str) -> Path:
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = upload_dir / filename
        counter = 1
        while candidate.exists():
            candidate = upload_dir / f"{stem}-{counter}{suffix}"
            counter += 1
        return candidate

    @staticmethod
    def _renumber_upload_sources(
        *,
        job_id: str,
        sources: list[Source],
        existing_sources: list[Source],
    ) -> list[Source]:
        start = UploadService._next_upload_index(job_id, existing_sources)
        renumbered: list[Source] = []
        for offset, source in enumerate(sources, start=start):
            renumbered.append(
                source.model_copy(
                    update={
                        "id": f"{job_id}-upload-source-{offset}",
                        "citation_key": f"[Upload{offset}]",
                    }
                )
            )
        return renumbered

    @staticmethod
    def _next_upload_index(job_id: str, sources: list[Source]) -> int:
        prefix = f"{job_id}-upload-source-"
        indexes = [
            int(source.id.removeprefix(prefix))
            for source in sources
            if source.id.startswith(prefix) and source.id.removeprefix(prefix).isdigit()
        ]
        return max(indexes, default=0) + 1

    @staticmethod
    def _cleanup(paths: list[Path]) -> None:
        for path in paths:
            path.unlink(missing_ok=True)
