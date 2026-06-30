from fastapi.testclient import TestClient

from app.main import create_app
from app.config import get_settings
from schemas.reports import ReportDepth, ReportJob, ReportSection, ReportStatus, ReportType
from schemas.sources import Claim, Source, VerificationStatus


def test_create_job_endpoint_returns_job_id():
    client = TestClient(create_app())

    response = client.post(
        "/jobs",
        json={
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "nvidia",
        },
    )

    assert response.status_code == 202
    assert response.json()["job_id"]


def test_get_job_progress_endpoint_returns_status():
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "nvidia",
        },
    ).json()

    response = client.get(f"/jobs/{created['job_id']}/progress")

    assert response.status_code == 200
    assert response.json()["job_id"] == created["job_id"]


def test_missing_job_errors_are_stable():
    client = TestClient(create_app())

    response = client.get("/jobs/not-a-real-job/progress")

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


def test_upload_endpoint_indexes_uploaded_documents(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    get_settings.cache_clear()
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "nvidia",
        },
    ).json()

    response = client.post(
        f"/jobs/{created['job_id']}/uploads",
        files={
            "files": (
                "notes.txt",
                b"Uploaded evidence explains source-grounded AI reporting and export review.",
                "text/plain",
            )
        },
    )
    sources = client.get(f"/jobs/{created['job_id']}/sources")

    assert response.status_code == 201
    assert response.json()["source_ids"] == [f"{created['job_id']}-upload-source-1"]
    assert response.json()["chunks_indexed"] == 1
    assert sources.status_code == 200
    assert sources.json()[0]["citation_key"] == "[Upload1]"


def test_job_outputs_sources_sections_and_markdown_export(monkeypatch):
    def fake_fetch(url):
        return (
            "AI Reporting Source",
            (
                "The central takeaway is that AI reporting is moving from a research idea toward "
                "usable planning and control patterns. From a market perspective, the important "
                "signal is that language interfaces can lower the friction of programming and "
                "operating reports. Technically, the relevant shift is the connection between "
                "language understanding, task decomposition, and report action selection. The main "
                "risk is that impressive demonstrations can overstate readiness unless they are tied "
                "to reliable execution evidence. "
                "AI reporting systems use language models to gather source evidence, draft "
                "structured report sections, and verify claims against citations. The reporting "
                "workflow depends on source-grounded generation, traceable claims, cost tracking, "
                "and reviewable exports for business users. "
            )
            * 4,
        )

    monkeypatch.setattr("agents.research_agent.fetch_url_text", fake_fetch)
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "nvidia",
            "urls": ["https://example.com/ai-reporting?utm_source=test"],
        },
    ).json()

    sections = client.get(f"/jobs/{created['job_id']}/sections")
    sources = client.get(f"/jobs/{created['job_id']}/sources")
    export = client.get(f"/jobs/{created['job_id']}/export/markdown")

    assert sections.status_code == 200
    assert sections.json()
    assert len(sections.json()) >= 2
    assert sources.status_code == 200
    assert sources.json()
    assert export.status_code == 200
    assert "# AI reporting" in export.text


def test_export_endpoint_blocks_unfinished_jobs(monkeypatch):
    job, sources = _sample_export_job(status=ReportStatus.RUNNING)
    monkeypatch.setattr("app.routers.export.manager", _FakeExportManager(job, sources))
    client = TestClient(create_app())

    response = client.get(f"/jobs/{job.id}/export/markdown")

    assert response.status_code == 409
    assert "not ready for export" in response.json()["detail"]


def test_export_endpoint_returns_pdf_from_unified_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    job, sources = _sample_export_job()
    monkeypatch.setattr("app.routers.export.manager", _FakeExportManager(job, sources))
    client = TestClient(create_app())

    response = client.get(f"/jobs/{job.id}/export/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-1.4")


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model_ready"] is True


def test_quota_endpoint_returns_remaining_counts():
    client = TestClient(create_app())

    response = client.get("/costs/quota")

    assert response.status_code == 200
    assert "nvidia_requests_per_minute_remaining" in response.json()


class _FakeExportManager:
    def __init__(self, job: ReportJob, sources: list[Source]) -> None:
        self.jobs = {job.id: job}
        self._job = job
        self._sources = sources

    def get_job(self, job_id: str) -> ReportJob:
        return self._job

    def list_sources(self, job_id: str) -> list[Source]:
        return self._sources


def _sample_export_job(
    *,
    status: ReportStatus = ReportStatus.COMPLETED,
    claim_status: VerificationStatus = VerificationStatus.SUPPORTED,
) -> tuple[ReportJob, list[Source]]:
    source = Source(
        id="source-1",
        job_id="job-1",
        title="AI Reporting Source",
        url="https://example.com/report",
        raw_text="AI reporting evidence supports source-grounded exports.",
        citation_key="[Web1]",
    )
    claim = Claim(
        id="claim-1",
        section_id="section-1",
        text="AI reporting evidence supports source-grounded exports. [Web1]",
        source_ids=["source-1"],
        verification_status=claim_status,
    )
    section = ReportSection(
        id="section-1",
        job_id="job-1",
        title="Summary",
        content="## Summary\n\nAI reporting evidence supports source-grounded exports. [Web1]",
        order=0,
        status="drafted",
        sources=["source-1"],
        claims=[claim],
    )
    job = ReportJob(
        id="job-1",
        topic="AI reporting",
        type=ReportType.MARKET_RESEARCH,
        depth=ReportDepth.STANDARD,
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        sections=[section],
    )
    return job, [source]
