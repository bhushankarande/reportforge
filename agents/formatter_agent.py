"""Formatter agent for export artifacts."""

from pathlib import Path

from schemas.agent_outputs import FormatterOutput


class FormatterAgent:
    """Render report artifacts for supported formats."""

    def format(self, job_id: str, markdown: str, output_dir: str) -> FormatterOutput:
        """Write placeholder Markdown, PDF, and DOCX artifacts."""
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        markdown_path = root / f"{job_id}.md"
        pdf_path = root / f"{job_id}.pdf"
        docx_path = root / f"{job_id}.docx"
        markdown_path.write_text(markdown, encoding="utf-8")
        pdf_path.write_bytes(markdown.encode("utf-8"))
        docx_path.write_text(markdown, encoding="utf-8")
        return FormatterOutput(
            markdown_path=str(markdown_path),
            pdf_path=str(pdf_path),
            docx_path=str(docx_path),
        )
