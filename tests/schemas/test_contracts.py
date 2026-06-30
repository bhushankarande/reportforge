from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.agent_outputs import PlannerOutput, WriterInput
from schemas.api import CreateJobRequest, JobProgress
from schemas.costs import AgentTrace, CostMetrics
from schemas.reports import ReportDepth, ReportJob, ReportSection, ReportStatus, ReportType
from schemas.sources import Claim, EvidenceChunk, Source, VerificationStatus


def test_create_job_request_defaults_to_nvidia_and_empty_urls():
    request = CreateJobRequest(topic="AI reporting", type="market_research", depth="standard")

    assert request.provider == "nvidia"
    assert request.urls == []
    assert request.type == ReportType.MARKET_RESEARCH
    assert request.depth == ReportDepth.STANDARD


def test_create_job_request_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        CreateJobRequest(
            topic="AI reporting",
            type="market_research",
            depth="standard",
            provider="paid-provider",
        )


def test_report_section_accepts_known_runtime_statuses_only():
    for status in ("pending", "drafted", "blocked", "regenerated"):
        section = ReportSection(
            id=f"section-{status}",
            job_id="job-1",
            title="Overview",
            order=0,
            status=status,
        )

        assert section.status == status

    with pytest.raises(ValidationError):
        ReportSection(id="section-unknown", job_id="job-1", title="Overview", order=0, status="archived")


def test_claim_export_blocking_statuses_are_explicit():
    blocking = {VerificationStatus.UNSUPPORTED, VerificationStatus.CONTRADICTED}

    for status in VerificationStatus:
        claim = Claim(
            id=f"claim-{status.value.lower()}",
            section_id="section-1",
            text="Revenue increased.",
            source_ids=["source-1"],
            verification_status=status,
            confidence=0.8,
        )

        assert claim.blocks_export is (status in blocking)


def test_source_and_evidence_chunk_validate_citation_and_relevance_bounds():
    source = Source(
        id="source-1",
        job_id="job-1",
        title="Source",
        citation_key="[Source1]",
        relevance_score=1.0,
    )
    chunk = EvidenceChunk(
        id="chunk-1",
        job_id="job-1",
        source_id=source.id,
        text="Useful evidence.",
        chunk_index=0,
        relevance_score=0.5,
    )

    assert source.citation_key == "[Source1]"
    assert chunk.relevance_score == 0.5

    with pytest.raises(ValidationError):
        Source(id="bad-source", job_id="job-1", title="Bad", citation_key="Source1")
    with pytest.raises(ValidationError):
        EvidenceChunk(
            id="bad-chunk",
            job_id="job-1",
            source_id="source-1",
            text="Useful evidence.",
            chunk_index=-1,
        )


def test_cost_metrics_total_tokens_and_bounds():
    metrics = CostMetrics(
        prompt_tokens=12,
        completion_tokens=5,
        estimated_cost_usd=Decimal("0.00"),
    )

    assert metrics.total_tokens == 17

    with pytest.raises(ValidationError):
        CostMetrics(prompt_tokens=-1)


@pytest.mark.parametrize(
    "model",
    [
        lambda: CreateJobRequest(topic="AI reporting", type="market_research", depth="standard"),
        lambda: JobProgress(job_id="job-1", status=ReportStatus.PENDING),
        lambda: ReportJob(
            id="job-1",
            topic="AI reporting",
            type=ReportType.MARKET_RESEARCH,
            depth=ReportDepth.STANDARD,
            created_at="2026-06-26T00:00:00+00:00",
        ),
        lambda: PlannerOutput(outline=["Overview"], research_questions=["What changed?"]),
        lambda: WriterInput(job_id="job-1", section_title="Overview", evidence=[]),
        lambda: AgentTrace(
            id="trace-1",
            job_id="job-1",
            agent_name="PlannerAgent",
            input="in",
            output="out",
            timestamp="2026-06-26T00:00:00+00:00",
        ),
    ],
)
def test_schema_models_reject_unknown_fields(model):
    payload = model().model_dump()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        type(model()).model_validate(payload)
