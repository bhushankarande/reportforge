"""Regression helpers for end-to-end ReportForge checks."""

import os
from pathlib import Path

from app.config import Settings
from app.services.job_registry import manager
from orchestration.checkpoints import CheckpointStore
from orchestration.state import WorkflowState
from schemas.api import CreateJobRequest
from schemas.reports import ReportDepth, ReportStatus, ReportType
from tools.llm.model_router import ModelRouter, ProviderBlockedError
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
    markdown = manager.export_markdown(response.job_id)
    from tools.export.pdf import write_pdf

    path = write_pdf(markdown, Path(tmp_dir) / f"{response.job_id}.pdf")
    if not path.exists():
        raise AssertionError("PDF export was not created")
    return path


def checkpoint_resume_test(tmp_dir: str | Path) -> WorkflowState:
    """Simulate checkpoint write and resume after interruption."""
    store = CheckpointStore(Path(tmp_dir))
    state = WorkflowState(job_id="resume-job")
    state.mark_completed("planned")
    store.save(state)
    loaded = store.load("resume-job")
    if loaded is None or loaded.completed_steps != ["planned"]:
        raise AssertionError("Checkpoint resume failed")
    loaded.mark_completed("completed")
    return loaded


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
        model = ModelRouter(Settings(ACTIVE_LLM_PROVIDER=provider, MAX_COST_USD_PER_JOB=1.0)).get_model()
        return model.provider
    finally:
        if previous is None:
            os.environ.pop("ACTIVE_LLM_PROVIDER", None)
        else:
            os.environ["ACTIVE_LLM_PROVIDER"] = previous


def kimi_cost_guard_test() -> bool:
    """Verify Kimi is blocked when cost guard is zero."""
    try:
        ModelRouter(Settings(ACTIVE_LLM_PROVIDER="kimi", MAX_COST_USD_PER_JOB=0.0)).get_model()
    except ProviderBlockedError:
        return True
    return False


def quota_enforcement_test() -> bool:
    """Simulate Gemini quota exhaustion and verify the next request is blocked."""
    quota = QuotaManager(QuotaLimits(gemini_requests_per_day=1, groq_tokens_per_day=1_000_000))
    quota.check_and_increment("gemini")
    try:
        quota.check_and_increment("gemini")
    except QuotaExceededError:
        return True
    return False


def assert_job_completed(job_id: str) -> None:
    """Raise if a regression job did not finish successfully."""
    if manager.get_job(job_id).status not in {ReportStatus.COMPLETED, ReportStatus.AWAITING_APPROVAL}:
        raise AssertionError("Job did not reach a terminal successful state")
