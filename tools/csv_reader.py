"""CSV and spreadsheet parsing tool."""

from pathlib import Path


def read_tabular(path: str | Path) -> str:
    """Extract a markdown preview from CSV/XLSX using pandas when available."""
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except ImportError:
        return Path(path).read_text(errors="ignore")

    path_obj = Path(path)
    if path_obj.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path_obj)
    else:
        frame = pd.read_csv(path_obj)
    return frame.head(50).to_markdown(index=False)
