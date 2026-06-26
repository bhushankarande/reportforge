"""Shared report export policy and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from schemas.reports import ReportJob, ReportStatus
from schemas.sources import Source
from tools.export.markdown import render_markdown


class ExportBlockedError(ValueError):
    """Raised when a report is not allowed to export."""


class ExportFormatError(ValueError):
    """Raised when an export format is not supported."""


@dataclass(frozen=True)
class ExportArtifact:
    """A generated export artifact ready for an API response."""

    path: Path
    format: str
    media_type: str
    filename: str


FORMAT_ALIASES = {
    "markdown": "md",
    "md": "md",
    "pdf": "pdf",
    "docx": "docx",
}

MEDIA_TYPES = {
    "md": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def normalize_export_format(export_format: str) -> str:
    """Return canonical export format extension."""
    normalized = str(export_format or "").lower().strip().lstrip(".")
    try:
        return FORMAT_ALIASES[normalized]
    except KeyError as exc:
        raise ExportFormatError("unsupported export format") from exc


def assert_report_exportable(job: ReportJob) -> None:
    """Raise if a report is not ready or has blocking claims."""
    if job.status != ReportStatus.COMPLETED:
        raise ExportBlockedError(
            f"Report is not ready for export while status is '{job.status.value}'."
        )

    blockers = [
        claim.id for section in job.sections for claim in section.claims if claim.blocks_export
    ]
    if blockers:
        raise ExportBlockedError(f"export blocked by unsupported claims: {', '.join(blockers)}")


def render_report_markdown(job: ReportJob, sources: list[Source]) -> str:
    """Render export Markdown after applying shared export gates."""
    assert_report_exportable(job)
    sections = [section.content for section in job.sections]
    bibliography = [
        f"{source.citation_key} {source.title}" + (f" - {source.url}" if source.url else "")
        for source in sources
    ]
    return render_markdown(job.topic, sections, bibliography)


def export_filename(job: ReportJob, export_format: str) -> str:
    """Return the download filename for an export format."""
    extension = normalize_export_format(export_format)
    return f"{job.topic}.{extension}"
