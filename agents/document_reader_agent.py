"""Document reader agent for uploaded files."""

from pathlib import Path

from schemas.agent_outputs import DocumentReaderOutput
from tools.csv_reader import read_tabular
from tools.docx_reader import read_docx
from tools.pdf_reader import read_pdf


class DocumentReaderAgent:
    """Parse uploaded documents and report indexed chunk counts."""

    def read(self, paths: list[str]) -> DocumentReaderOutput:
        """Parse supported files and return source ids."""
        source_ids: list[str] = []
        chunks = 0
        for value in paths:
            path = Path(value)
            if path.suffix.lower() == ".pdf":
                text = read_pdf(path)
            elif path.suffix.lower() == ".docx":
                text = read_docx(path)
            elif path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
                text = read_tabular(path)
            else:
                text = path.read_text(errors="ignore")
            source_ids.append(path.stem)
            chunks += max(1, len(text) // 1000)
        return DocumentReaderOutput(source_ids=source_ids, chunks_indexed=chunks)
