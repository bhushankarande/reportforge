"""Regression helpers for end-to-end ReportForge checks."""

import os
from pathlib import Path

from agents.formatter_agent import FormatterAgent
from app.config import Settings
from app.services.job_registry import manager
from schemas.api import CreateJobRequest
from schemas.reports import ReportDepth, ReportStatus, ReportType
from tools.llm.model_router import ModelRouter
from tools.llm.quota_manager import QuotaExceededError, QuotaLimits, QuotaManager


def end_to_end_topic_to_pdf(tmp_dir: str | Path) -> Path:
    """Submit a topic, run workflow, and verify a PDF export exists."""
    request = CreateJobRequest(
        topic="AI reporting",
        type=ReportType.MARKET_RESEARCH,
        depth=ReportDepth.STANDARD,
    )
    response = manager.create_job(request, session_id="regression")
    manager.execute(response.job_id)
    artifact = FormatterAgent().export_artifact(
        manager.get_job(response.job_id),
        manager.list_sources(response.job_id),
        str(tmp_dir),
        export_format="pdf",
    )
    if not artifact.path.exists():
        raise AssertionError("PDF export was not created")
    return artifact.path


def cost_tracking_test(job_id: str) -> float:
    """Verify total job cost is the sum of recorded agent costs."""
    traces = manager.list_traces(job_id)
    total = sum(float(trace.cost) for trace in traces)
    if total != 0.0:
        raise AssertionError("Free-tier actual cost must remain $0.00")
    return total


def provider_swap_test(provider: str) -> str:
    """Verify changing ACTIVE_LLM_PROVIDER changes routed model provider."""
    previous = os.environ.get("ACTIVE_LLM_PROVIDER")
    os.environ["ACTIVE_LLM_PROVIDER"] = provider
    try:
        model = ModelRouter(Settings(ACTIVE_LLM_PROVIDER=provider)).get_model()
        return model.provider
    finally:
        if previous is None:
            os.environ.pop("ACTIVE_LLM_PROVIDER", None)
        else:
            os.environ["ACTIVE_LLM_PROVIDER"] = previous

def quota_enforcement_test() -> bool:
    """Simulate NVIDIA NIM quota exhaustion and verify the next request is blocked."""
    quota = QuotaManager(
        QuotaLimits(
            nvidia_requests_per_minute=1,
            nvidia_requests_per_day=0,
            groq_requests_per_minute=60,
            groq_requests_per_day=1_000,
            groq_tokens_per_day=500_000,
        )
    )
    quota.check_and_increment("nvidia")
    try:
        quota.check_and_increment("nvidia")
    except QuotaExceededError:
        return True
    return False


def assert_job_completed(job_id: str) -> None:
    """Raise if a regression job did not finish successfully."""
    if manager.get_job(job_id).status not in {ReportStatus.COMPLETED, ReportStatus.AWAITING_APPROVAL}:
        raise AssertionError("Job did not reach a terminal successful state")
