"""PDF export helper."""

from pathlib import Path


def write_pdf_placeholder(markdown: str, path: str | Path) -> Path:
    """Write a lightweight PDF placeholder for MVP tests."""
    output = Path(path)
    output.write_bytes(markdown.encode("utf-8"))
    return output
