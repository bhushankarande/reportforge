"""Formatter agent for export artifacts."""

from pathlib import Path

from schemas.agent_outputs import FormatterOutput
from tools.export.docx import write_docx
from tools.export.pdf import write_pdf


class FormatterAgent:
    """Render report artifacts for supported formats."""

    def format(self, job_id: str, markdown: str, output_dir: str) -> FormatterOutput:
        """Write Markdown, PDF, and DOCX artifacts."""
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        markdown_path = root / f"{job_id}.md"
        pdf_path = root / f"{job_id}.pdf"
        docx_path = root / f"{job_id}.docx"
        markdown_path.write_text(markdown, encoding="utf-8")
        write_pdf(markdown, pdf_path)
        write_docx(markdown, docx_path)
        return FormatterOutput(
            markdown_path=str(markdown_path),
            pdf_path=str(pdf_path),
            docx_path=str(docx_path),
        )
