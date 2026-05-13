"""DOCX parsing tool."""

from pathlib import Path


def read_docx(path: str | Path) -> str:
    """Extract text from a DOCX using python-docx when available."""
    try:
        import docx  # type: ignore[import-not-found]
    except ImportError:
        return Path(path).read_text(errors="ignore")

    document = docx.Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
