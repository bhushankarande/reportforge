"""Chart generation helpers."""

from pathlib import Path


def save_chart_placeholder(job_id: str, title: str, output_dir: str | Path = "storage/charts") -> Path:
    """Save a placeholder chart artifact."""
    root = Path(output_dir) / job_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{title.lower().replace(' ', '-')}.txt"
    path.write_text("chart placeholder", encoding="utf-8")
    return path
