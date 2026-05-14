"""CSV and spreadsheet parsing tool."""

from __future__ import annotations

from pathlib import Path

from app.logging_config import get_logger
from tools.pdf_reader import DocumentParseError

logger = get_logger(__name__)


def read_tabular(path: str | Path, *, max_rows: int = 100, max_columns: int = 50) -> str:
    """Extract a Markdown preview and schema summary from CSV/XLS/XLSX data."""
    path_obj = Path(path)
    _assert_readable_file(path_obj, {".csv", ".xlsx", ".xls"})

    try:
        import pandas as pd
    except ImportError as exc:
        raise DocumentParseError("pandas is required to parse tabular files. Run: uv add pandas openpyxl") from exc

    try:
        if path_obj.suffix.lower() in {".xlsx", ".xls"}:
            frame = pd.read_excel(path_obj)
        else:
            frame = pd.read_csv(path_obj)
    except Exception as exc:
        logger.exception("tabular_read_failed", path=str(path_obj), error=str(exc))
        raise DocumentParseError(f"Could not parse tabular file: {path_obj}") from exc

    if frame.empty:
        raise DocumentParseError(f"Tabular file has no rows: {path_obj}")

    preview = frame.iloc[:max_rows, :max_columns].copy()
    schema_lines = [
        f"Rows: {len(frame)}",
        f"Columns: {len(frame.columns)}",
        "Column types:",
        *[f"- {column}: {dtype}" for column, dtype in frame.dtypes.items()],
    ]
    markdown = preview.to_markdown(index=False)
    text = "\n".join(schema_lines) + "\n\nPreview:\n" + markdown

    logger.info("tabular_parsed", path=str(path_obj), rows=len(frame), columns=len(frame.columns))
    return text


def _assert_readable_file(path: Path, allowed_suffixes: set[str]) -> None:
    """Validate that a path exists, is a file, and has an allowed suffix."""
    if not path.exists():
        raise DocumentParseError(f"File does not exist: {path}")
    if not path.is_file():
        raise DocumentParseError(f"Path is not a file: {path}")
    if path.suffix.lower() not in allowed_suffixes:
        raise DocumentParseError(f"Unsupported file type for {path}")
