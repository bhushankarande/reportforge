"""Document reader agent for uploaded files."""

from __future__ import annotations

from pathlib import Path

from app.logging_config import get_logger
from schemas.agent_outputs import DocumentReaderOutput
from tools.csv_reader import read_tabular
from tools.docx_reader import read_docx
from tools.pdf_reader import DocumentParseError, read_pdf
from tools.rag.evidence_pipeline import EvidencePipeline, EvidencePipelineResult, RawEvidence

logger = get_logger(__name__)


class DocumentReaderAgent:
    """Parse uploaded documents and report indexed chunk counts."""

    SUPPORTED_SUFFIXES = {".pdf", ".docx", ".csv", ".xlsx", ".xls", ".txt", ".md"}

    def read(self, paths: list[str]) -> DocumentReaderOutput:
        """Parse supported files and return source ids plus chunk counts."""
        source_ids: list[str] = []
        chunks = 0

        for value in paths:
            path = Path(value)
            text = self._read_text(path)

            source_ids.append(path.stem)
            chunks += self._chunk_count(text)

        logger.info("documents_parsed", files=len(paths), chunks=chunks)
        return DocumentReaderOutput(source_ids=source_ids, chunks_indexed=chunks)

    def read_evidence(self, job_id: str, paths: list[str]) -> EvidencePipelineResult:
        """Parse supported files into normalized evidence and an indexed retriever."""
        evidence_items: list[RawEvidence] = []

        for value in paths:
            path = Path(value)
            evidence_items.append(
                RawEvidence(
                    source_type="upload",
                    title=path.name,
                    text=self._read_text(path),
                )
            )

        result = EvidencePipeline(job_id).ingest(evidence_items)
        logger.info(
            "documents_evidence_indexed", files=len(result.sources), chunks=len(result.chunks)
        )
        return result

    def _read_text(self, path: Path) -> str:
        try:
            return self._read_one(path)
        except DocumentParseError:
            raise
        except Exception as exc:
            logger.exception("document_reader_failed", path=str(path), error=str(exc))
            raise DocumentParseError(f"Could not parse uploaded document: {path}") from exc

    def _read_one(self, path: Path) -> str:
        """Read one supported document path."""
        if not path.exists():
            raise DocumentParseError(f"File does not exist: {path}")
        if not path.is_file():
            raise DocumentParseError(f"Path is not a file: {path}")

        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise DocumentParseError(f"Unsupported uploaded file type: {suffix or '<none>'}")

        if suffix == ".pdf":
            return read_pdf(path)
        if suffix == ".docx":
            return read_docx(path)
        if suffix in {".csv", ".xlsx", ".xls"}:
            return read_tabular(path)
        return path.read_text(encoding="utf-8", errors="replace").strip()

    @staticmethod
    def _chunk_count(text: str, *, chunk_size: int = 1_000) -> int:
        """Estimate indexed chunk count from extracted text length."""
        if not text:
            return 0
        return max(1, (len(text) + chunk_size - 1) // chunk_size)
