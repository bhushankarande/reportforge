from zipfile import ZipFile

from agents.data_analyst_agent import DataAnalystAgent
from agents.formatter_agent import FormatterAgent
from tools.export.docx import write_docx
from tools.export.pdf import write_pdf


def test_pdf_writer_creates_valid_pdf_header(tmp_path):
    path = write_pdf("# Report\n\nEvidence [SourceID]", tmp_path / "report.pdf")

    assert path.read_bytes().startswith(b"%PDF-1.4")


def test_pdf_writer_creates_multiple_pages_for_long_reports(tmp_path):
    markdown = "\n".join(f"Line {index}" for index in range(120))

    path = write_pdf(markdown, tmp_path / "long-report.pdf")

    assert b"/Count 3" in path.read_bytes()


def test_docx_writer_creates_office_zip(tmp_path):
    path = write_docx("# Report\n\nEvidence [SourceID]", tmp_path / "report.docx")

    with ZipFile(path) as archive:
        assert "word/document.xml" in archive.namelist()


def test_formatter_agent_writes_all_artifacts(tmp_path):
    output = FormatterAgent().format("job-1", "# Report", str(tmp_path))

    assert output.markdown_path
    assert output.pdf_path
    assert output.docx_path


def test_data_analyst_agent_summarizes_csv(tmp_path):
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("name,value\nA,1\nB,3\n", encoding="utf-8")

    output = DataAnalystAgent().analyze(str(csv_path), str(tmp_path / "charts"))

    assert output["charts"]
    assert output["insights"] == ["Analyzed 2 rows from metrics.csv."]
