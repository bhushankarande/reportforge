"""Data analyst agent for chart and insight generation."""

from pathlib import Path

from tools.charts.generation import load_csv_rows, save_chart_summary


class DataAnalystAgent:
    """Create basic chart artifacts and insights from tabular data."""

    def analyze(self, csv_path: str, output_dir: str) -> dict[str, list[str]]:
        """Return chart paths and lightweight insights for CSV data."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        rows = load_csv_rows(csv_path)
        chart_path = save_chart_summary("analysis", Path(csv_path).stem, rows, output_dir)
        return {
            "charts": [str(chart_path)],
            "insights": [f"Analyzed {len(rows)} rows from {Path(csv_path).name}."],
        }
