"""Data analyst agent for chart and insight generation."""

from pathlib import Path


class DataAnalystAgent:
    """Create basic chart artifacts and insights from tabular data."""

    def analyze(self, csv_path: str, output_dir: str) -> dict[str, list[str]]:
        """Return chart paths and lightweight insights."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        chart_path = Path(output_dir) / f"{Path(csv_path).stem}.txt"
        chart_path.write_text("chart placeholder", encoding="utf-8")
        return {"charts": [str(chart_path)], "insights": ["Data analysis completed."]}
