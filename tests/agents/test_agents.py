from agents.planner_agent import PlannerAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from schemas.agent_outputs import WriterInput


def test_planner_agent_returns_outline():
    output = PlannerAgent().plan("AI reporting", "market_research", "standard")

    assert output.outline
    assert output.research_questions


def test_writer_and_verifier_keep_sourced_claim_exportable():
    draft = ReportWriterAgent().write(
        WriterInput(job_id="job-1", section_title="Summary", evidence=["Evidence text"])
    )
    verified = VerifierAgent().verify(draft.claims)

    assert not verified.blockers
    assert verified.claims[0].source_ids
