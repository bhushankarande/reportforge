"""Formatter agent for export artifacts.

This formatter safely renders Markdown, PDF, and DOCX artifacts.

It remains backward-compatible with:

    format(job_id: str, markdown: str, output_dir: str) -> FormatterOutput

Improvements:
- sanitizes job_id before using it as a filename,
- prevents path traversal,
- writes files atomically through temporary files,
- supports requested formats,
- validates empty Markdown,
- cleans up partial failed exports,
- logs export failures clearly.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from app.logging_config import get_logger
from schemas.agent_outputs import FormatterOutput
from schemas.reports import ReportJob
from schemas.sources import Source
from tools.export.docx import write_docx
from tools.export.pdf import write_pdf
from tools.export.report import (
    ExportArtifact,
    MEDIA_TYPES,
    export_filename,
    normalize_export_format,
    render_report_markdown,
)

logger = get_logger(__name__)


class FormatterAgent:
    """Render report artifacts for supported formats."""

    SUPPORTED_FORMATS = {"md", "pdf", "docx"}

    def format_report(
        self,
        job: ReportJob,
        sources: list[Source],
        output_dir: str,
        *,
        export_format: str,
    ) -> FormatterOutput:
        """Render one report export through the shared export policy."""
        normalized_format = normalize_export_format(export_format)
        markdown = render_report_markdown(job, sources)
        return self.format(job.id, markdown, output_dir, formats=[normalized_format])

    def export_artifact(
        self,
        job: ReportJob,
        sources: list[Source],
        output_dir: str,
        *,
        export_format: str,
    ) -> ExportArtifact:
        """Render one report export and return artifact metadata."""
        normalized_format = normalize_export_format(export_format)
        output = self.format_report(
            job,
            sources,
            output_dir,
            export_format=normalized_format,
        )
        path_by_format = {
            "md": output.markdown_path,
            "pdf": output.pdf_path,
            "docx": output.docx_path,
        }
        return ExportArtifact(
            path=Path(path_by_format[normalized_format]),
            format=normalized_format,
            media_type=MEDIA_TYPES[normalized_format],
            filename=export_filename(job, normalized_format),
        )

    def format(
        self,
        job_id: str,
        markdown: str,
        output_dir: str,
        *,
        formats: Iterable[str] | None = None,
    ) -> FormatterOutput:
        """Write requested report artifacts.

        Args:
            job_id: Stable job identifier used for filenames.
            markdown: Final report Markdown.
            output_dir: Directory where artifacts should be written.
            formats: Optional iterable of requested formats.
                Defaults to {"md", "pdf", "docx"} for backward compatibility.

        Returns:
            FormatterOutput containing artifact paths.

        Raises:
            ValueError: If input is invalid.
            RuntimeError: If one or more exports fail.
        """
        safe_job_id = self._safe_job_id(job_id)
        clean_markdown = self._validate_markdown(markdown)
        requested_formats = self._normalize_formats(formats)

        root = Path(output_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        markdown_path = root / f"{safe_job_id}.md"
        pdf_path = root / f"{safe_job_id}.pdf"
        docx_path = root / f"{safe_job_id}.docx"

        self._ensure_paths_inside_root(
            root=root,
            paths=[markdown_path, pdf_path, docx_path],
        )

        written_paths: list[Path] = []

        try:
            if "md" in requested_formats:
                self._atomic_write_text(markdown_path, clean_markdown)
                written_paths.append(markdown_path)

            if "pdf" in requested_formats:
                self._atomic_export_binary(
                    final_path=pdf_path,
                    export_func=lambda temp_path: write_pdf(clean_markdown, temp_path),
                )
                written_paths.append(pdf_path)

            if "docx" in requested_formats:
                self._atomic_export_binary(
                    final_path=docx_path,
                    export_func=lambda temp_path: write_docx(clean_markdown, temp_path),
                )
                written_paths.append(docx_path)

        except Exception as exc:
            self._cleanup_paths(written_paths)

            logger.exception(
                "formatter_export_failed",
                job_id=job_id,
                safe_job_id=safe_job_id,
                requested_formats=sorted(requested_formats),
                error_type=type(exc).__name__,
                error=str(exc),
            )

            raise RuntimeError(
                f"Failed to export report artifacts for job '{safe_job_id}': "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        logger.info(
            "formatter_export_completed",
            job_id=job_id,
            safe_job_id=safe_job_id,
            requested_formats=sorted(requested_formats),
            artifact_count=len(written_paths),
        )

        return FormatterOutput(
            markdown_path=str(markdown_path) if "md" in requested_formats else "",
            pdf_path=str(pdf_path) if "pdf" in requested_formats else "",
            docx_path=str(docx_path) if "docx" in requested_formats else "",
        )

    def _safe_job_id(self, job_id: str) -> str:
        """Return a filesystem-safe job ID."""
        raw = str(job_id or "").strip()

        if not raw:
            raise ValueError("job_id cannot be empty.")

        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
        safe = safe.strip("._-")

        if not safe:
            raise ValueError("job_id does not contain any safe filename characters.")

        return safe[:120]

    def _validate_markdown(self, markdown: str) -> str:
        """Validate and normalize Markdown before export."""
        if markdown is None:
            raise ValueError("markdown cannot be None.")

        clean = str(markdown).strip()

        if not clean:
            raise ValueError("Cannot export an empty report.")

        unresolved_markers = [
            "[SourceID]",
            "[citation needed]",
            "{{",
            "}}",
            "TODO",
            "TBD",
        ]

        found_markers = [marker for marker in unresolved_markers if marker.lower() in clean.lower()]

        if found_markers:
            raise ValueError(
                "Cannot export report with unresolved placeholders: " + ", ".join(found_markers)
            )

        return clean + "\n"

    def _normalize_formats(self, formats: Iterable[str] | None) -> set[str]:
        """Normalize requested export formats."""
        if formats is None:
            return set(self.SUPPORTED_FORMATS)

        normalized = {str(fmt).lower().strip().lstrip(".") for fmt in formats if str(fmt).strip()}

        if not normalized:
            raise ValueError("At least one export format must be requested.")

        unsupported = normalized - self.SUPPORTED_FORMATS

        if unsupported:
            raise ValueError(
                f"Unsupported export format(s): {sorted(unsupported)}. "
                f"Supported formats: {sorted(self.SUPPORTED_FORMATS)}."
            )

        return normalized

    def _ensure_paths_inside_root(self, *, root: Path, paths: list[Path]) -> None:
        """Prevent path traversal or accidental writes outside output_dir."""
        root_resolved = root.resolve()

        for path in paths:
            resolved = path.resolve()

            if root_resolved not in [resolved, *resolved.parents]:
                raise ValueError(f"Unsafe export path detected: {resolved}")

    def _atomic_write_text(self, final_path: Path, text: str) -> None:
        """Atomically write text to final_path."""
        final_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=final_path.suffix,
            dir=final_path.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(text)

        temp_path.replace(final_path)

    def _atomic_export_binary(
        self,
        *,
        final_path: Path,
        export_func: Callable[[Path], object],
    ) -> None:
        """Atomically export PDF/DOCX through a temporary file."""
        final_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            suffix=final_path.suffix,
            dir=final_path.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            export_func(temp_path)

            if not temp_path.exists():
                raise RuntimeError(f"Exporter did not create expected file: {temp_path}")

            if temp_path.stat().st_size == 0:
                raise RuntimeError(f"Exporter created an empty file: {temp_path}")

            temp_path.replace(final_path)

        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def _cleanup_paths(self, paths: list[Path]) -> None:
        """Remove artifacts written during a failed export."""
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "formatter_cleanup_failed",
                    path=str(path),
                )
