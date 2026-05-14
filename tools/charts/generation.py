"""Chart generation helpers."""

import csv
import json
from pathlib import Path


def save_chart_summary(
    job_id: str,
    title: str,
    rows: list[dict[str, str]],
    output_dir: str | Path = "storage/charts",
) -> Path:
    """Save a JSON chart-summary artifact from tabular rows."""
    root = Path(output_dir) / job_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{title.lower().replace(' ', '-')}.json"
    numeric_columns = _numeric_columns(rows)
    payload = {
        "title": title,
        "row_count": len(rows),
        "numeric_columns": numeric_columns,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_csv_rows(path: str | Path) -> list[dict[str, str]]:
    """Load CSV rows using the standard library."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _numeric_columns(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    """Return min, max, and average for numeric CSV columns."""
    values_by_column: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            values_by_column.setdefault(key, []).append(number)
    return {
        key: {"min": min(values), "max": max(values), "avg": sum(values) / len(values)}
        for key, values in values_by_column.items()
        if values
    }
