"""DOCX export helper."""

from pathlib import Path


def write_docx_placeholder(markdown: str, path: str | Path) -> Path:
    """Write a lightweight DOCX placeholder for MVP tests."""
    output = Path(path)
    output.write_text(markdown, encoding="utf-8")
    return output
