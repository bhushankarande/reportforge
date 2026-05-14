"""PDF parsing tool."""

from __future__ import annotations

from pathlib import Path
import re

from app.logging_config import get_logger

logger = get_logger(__name__)


class DocumentParseError(RuntimeError):
    """Raised when a document cannot be parsed into useful text."""


def read_pdf(path: str | Path, *, max_pages: int = 100) -> str:
    """Extract normalized text from a PDF using pypdf."""
    path_obj = Path(path)
    _assert_readable_file(path_obj, {".pdf"})

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("pypdf is required to parse PDFs. Run: uv add pypdf") from exc

    try:
        reader = PdfReader(str(path_obj))
    except Exception as exc:
        logger.exception("pdf_open_failed", path=str(path_obj), error=str(exc))
        raise DocumentParseError(f"Could not open PDF: {path_obj}") from exc

    pages: list[str] = []
    for page_index, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("pdf_page_extract_failed", path=str(path_obj), page=page_index, error=str(exc))
            continue
        page_text = _normalize_text(page_text)
        if page_text:
            pages.append(f"[Page {page_index}]\n{page_text}")

    text = "\n\n".join(pages).strip()
    if not text:
        raise DocumentParseError(f"No readable text extracted from PDF: {path_obj}")

    logger.info("pdf_parsed", path=str(path_obj), pages=min(len(reader.pages), max_pages), chars=len(text))
    return text


def _assert_readable_file(path: Path, allowed_suffixes: set[str]) -> None:
    """Validate that a path exists, is a file, and has an allowed suffix."""
    if not path.exists():
        raise DocumentParseError(f"File does not exist: {path}")
    if not path.is_file():
        raise DocumentParseError(f"Path is not a file: {path}")
    if path.suffix.lower() not in allowed_suffixes:
        raise DocumentParseError(f"Unsupported file type for {path}")


def _normalize_text(text: str) -> str:
    """Normalize extracted text while preserving paragraph breaks."""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
