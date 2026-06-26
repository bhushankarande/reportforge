from zipfile import ZipFile

import pytest

from agents.data_analyst_agent import DataAnalystAgent
from agents.formatter_agent import FormatterAgent
from schemas.reports import ReportDepth, ReportJob, ReportSection, ReportStatus, ReportType
from schemas.sources import Claim, Source, VerificationStatus
from tools.export.report import ExportBlockedError, assert_report_exportable
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


def test_formatter_agent_exports_report_through_shared_path(tmp_path):
    job, sources = _sample_exportable_report()

    output = FormatterAgent().format_report(job, sources, str(tmp_path), export_format="pdf")

    assert output.pdf_path
    assert not output.markdown_path
    assert not output.docx_path
    assert (tmp_path / "job-1.pdf").read_bytes().startswith(b"%PDF-1.4")


def test_report_export_blocks_non_completed_jobs():
    job, _sources = _sample_exportable_report(status=ReportStatus.AWAITING_APPROVAL)

    with pytest.raises(ExportBlockedError, match="not ready for export"):
        assert_report_exportable(job)


def test_report_export_blocks_unsupported_and_contradicted_claims():
    for status in [VerificationStatus.UNSUPPORTED, VerificationStatus.CONTRADICTED]:
        job, _sources = _sample_exportable_report(claim_status=status)

        with pytest.raises(ExportBlockedError, match="export blocked"):
            assert_report_exportable(job)


def test_data_analyst_agent_summarizes_csv(tmp_path):
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("name,value\nA,1\nB,3\n", encoding="utf-8")

    output = DataAnalystAgent().analyze(str(csv_path), str(tmp_path / "charts"))

    assert output["charts"]
    assert output["schema"]
    assert "metrics: analyzed 2 rows and 2 columns." in output["insights"]
    assert any("value ranges from" in insight for insight in output["insights"])


def _sample_exportable_report(
    *,
    status: ReportStatus = ReportStatus.COMPLETED,
    claim_status: VerificationStatus = VerificationStatus.SUPPORTED,
) -> tuple[ReportJob, list[Source]]:
    source = Source(
        id="source-1",
        job_id="job-1",
        title="Robotics Source",
        url="https://example.com/report",
        raw_text="Robotics evidence supports planning workflows.",
        citation_key="[Web1]",
    )
    claim = Claim(
        id="claim-1",
        section_id="section-1",
        text="Robotics evidence supports planning workflows. [Web1]",
        source_ids=["source-1"],
        verification_status=claim_status,
    )
    section = ReportSection(
        id="section-1",
        job_id="job-1",
        title="Summary",
        content="## Summary\n\nRobotics evidence supports planning workflows. [Web1]",
        order=0,
        status="drafted",
        sources=["source-1"],
        claims=[claim],
    )
    job = ReportJob(
        id="job-1",
        topic="Robotics report",
        type=ReportType.MARKET_RESEARCH,
        depth=ReportDepth.STANDARD,
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        sections=[section],
    )
    return job, [source]
