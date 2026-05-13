"""PDF parsing tool."""

from pathlib import Path


def read_pdf(path: str | Path) -> str:
    """Extract text from a PDF using pymupdf when available."""
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return Path(path).read_text(errors="ignore")

    document = fitz.open(path)
    return "\n".join(page.get_text() for page in document)
