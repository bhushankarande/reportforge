from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.report_store import ReportStore
from orchestration.job_manager import JobManager
from schemas.costs import AgentTrace, CostMetrics
from schemas.reports import ReportDepth, ReportJob, ReportSection, ReportStatus, ReportType
from schemas.sources import Claim, Source, VerificationStatus


@pytest.fixture
def report_store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reportforge.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return ReportStore(session_factory)


def test_report_store_loads_saved_job_sections_sources_and_traces(report_store):
    job, sources, trace = _sample_report()

    report_store.save_job_inputs(job.id, urls=["https://example.com/report"], provider="groq")
    report_store.save_job(job)
    report_store.save_sources(job.id, sources)
    report_store.add_trace(trace)

    loaded = report_store.load_report(job.id)

    assert loaded is not None
    assert loaded.provider == "groq"
    assert loaded.urls == ["https://example.com/report"]
    assert loaded.job.id == job.id
    assert loaded.job.status == ReportStatus.COMPLETED
    assert loaded.job.sections[0].title == "Market Signals"
    assert loaded.job.sections[0].claims[0].verification_status == VerificationStatus.SUPPORTED
    assert loaded.sources[0].citation_key == "[Source1]"
    assert loaded.traces[0].agent_name == "VerifierAgent"


def test_report_store_maps_legacy_gemini_inputs_to_nvidia(report_store):
    job, sources, trace = _sample_report()
    report_store.save_job_inputs(job.id, urls=["https://example.com/report"], provider="gemini")
    report_store.save_job(job)
    report_store.save_sources(job.id, sources)
    report_store.add_trace(trace)

    loaded = report_store.load_report(job.id)

    assert loaded is not None
    assert loaded.provider == "nvidia"


def test_job_manager_rehydrates_saved_report_state(report_store):
    job, sources, trace = _sample_report()
    report_store.save_job_inputs(job.id, urls=["https://example.com/report"], provider="groq")
    report_store.save_job(job)
    report_store.save_sources(job.id, sources)
    report_store.add_trace(trace)

    manager = JobManager(store=report_store)

    loaded_job = manager.get_job(job.id)

    assert loaded_job.sections[0].content == "Revenue increased with source support. [Source1]"
    assert manager.list_sources(job.id)[0].id == "source-1"
    assert manager.list_traces(job.id)[0].id == "trace-1"
    assert manager.progress(job.id).status == ReportStatus.COMPLETED
    assert manager.providers_by_job[job.id] == "groq"
    assert manager.urls_by_job[job.id] == ["https://example.com/report"]


def _sample_report() -> tuple[ReportJob, list[Source], AgentTrace]:
    claim = Claim(
        id="claim-1",
        section_id="section-1",
        text="Revenue increased with source support.",
        source_ids=["source-1"],
        verification_status=VerificationStatus.SUPPORTED,
        confidence=0.9,
    )
    section = ReportSection(
        id="section-1",
        job_id="job-1",
        title="Market Signals",
        content="Revenue increased with source support. [Source1]",
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
        status=ReportStatus.COMPLETED,
        cost=CostMetrics(
            prompt_tokens=10,
            estimated_cost_usd=Decimal("0.00"),
            model_name="qwen/qwen3-32b",
        ),
        created_at="2026-06-26T00:00:00+00:00",
        completed_at="2026-06-26T00:01:00+00:00",
        sections=[section],
    )
    source = Source(
        id="source-1",
        job_id=job.id,
        title="AI Reporting Source",
        url="https://example.com/report",
        summary="A useful source.",
        relevance_score=0.8,
        raw_text="Revenue increased with source support.",
        citation_key="[Source1]",
    )
    trace = AgentTrace(
        id="trace-1",
        job_id=job.id,
        agent_name="VerifierAgent",
        input="claim",
        output="supported",
        tokens=10,
        timestamp="2026-06-26T00:01:00+00:00",
    )
    return job, [source], trace
