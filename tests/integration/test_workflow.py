from orchestration.workflow import ReportWorkflow
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
