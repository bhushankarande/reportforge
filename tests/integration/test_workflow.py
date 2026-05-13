from orchestration.workflow import ReportWorkflow
from orchestration.checkpoints import CheckpointStore
from orchestration.state import WorkflowState
from schemas.reports import ReportDepth, ReportType


def test_report_workflow_completes_minimal_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    state = ReportWorkflow().run(
        job_id="job-1",
        topic="AI reporting",
        report_type=ReportType.MARKET_RESEARCH,
        depth=ReportDepth.STANDARD,
    )

    assert "planned" in state.completed_steps
    assert "researched" in state.completed_steps
    assert "written" in state.completed_steps


def test_checkpoint_write_and_resume(tmp_path):
    store = CheckpointStore(tmp_path)
    state = WorkflowState(job_id="job-1")
    state.mark_completed("planned")

    store.save(state)
    loaded = store.load("job-1")

    assert loaded is not None
    assert loaded.completed_steps == ["planned"]
