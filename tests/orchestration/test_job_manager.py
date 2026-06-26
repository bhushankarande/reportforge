import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.report_store import ReportStore
from orchestration.job_manager import JobManager, JobRunResult
from schemas.api import CreateJobRequest
from schemas.reports import ReportDepth, ReportSection, ReportStatus, ReportType
from schemas.sources import Source


@pytest.fixture
def report_store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reportforge.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return ReportStore(session_factory)


def test_run_job_marks_failed_jobs_explicitly(report_store):
    manager = JobManager(store=report_store, pipeline=FailingPipeline())
    created = manager.create_job(
        CreateJobRequest(topic="AI reporting", type=ReportType.MARKET_RESEARCH, depth=ReportDepth.STANDARD)
    )

    manager.run_job(created.job_id)

    job = manager.get_job(created.job_id)
    progress = manager.progress(created.job_id)
    stored = report_store.load_report(created.job_id)

    assert job.status == ReportStatus.FAILED
    assert progress.status == ReportStatus.FAILED
    assert progress.current_step == "pipeline failed"
    assert progress.percent_complete == 100.0
    assert stored is not None
    assert stored.job.status == ReportStatus.FAILED


def test_retry_resets_failed_job_and_runs_pipeline_again(report_store):
    pipeline = FlakyPipeline()
    manager = JobManager(store=report_store, pipeline=pipeline)
    created = manager.create_job(
        CreateJobRequest(
            topic="AI reporting",
            type=ReportType.MARKET_RESEARCH,
            depth=ReportDepth.STANDARD,
            urls=["https://example.com/report"],
        )
    )

    manager.run_job(created.job_id)
    manager.retry(created.job_id)

    job = manager.get_job(created.job_id)
    stored = report_store.load_report(created.job_id)

    assert pipeline.calls == 2
    assert job.status == ReportStatus.COMPLETED
    assert manager.progress(created.job_id).current_step == "completed"
    assert job.sections[0].title == "Recovered Section"
    assert manager.list_sources(created.job_id)[0].citation_key == "[Recovered]"
    assert stored is not None
    assert stored.job.status == ReportStatus.COMPLETED
    assert stored.sources[0].citation_key == "[Recovered]"


class FailingPipeline:
    def run(self, **kwargs):
        raise RuntimeError("pipeline failed")


class FlakyPipeline:
    def __init__(self):
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("pipeline failed")
        job = kwargs["job"]
        source = Source(
            id=f"{job.id}-source-1",
            job_id=job.id,
            title="Recovered Source",
            url="https://example.com/report",
            raw_text="Recovered evidence.",
            citation_key="[Recovered]",
        )
        section = ReportSection(
            id=f"{job.id}-section-1",
            job_id=job.id,
            title="Recovered Section",
            content="Recovered evidence. [Recovered]",
            order=0,
            status="drafted",
            sources=[source.id],
        )
        return JobRunResult(status=ReportStatus.COMPLETED, sections=[section], sources=[source])
