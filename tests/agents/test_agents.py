from unittest.mock import Mock

from faker import Faker

from agents.planner_agent import PlannerAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from schemas.agent_outputs import WriterInput
from tools.llm.model_router import RoutedModel


fake = Faker()


class FakeRouter:
    def get_model(self, provider=None):
        return RoutedModel(provider=provider or "gemini", model_name="gemini-1.5-flash")


def test_planner_agent_returns_outline():
    output = PlannerAgent(FakeRouter()).plan(fake.catch_phrase(), "market_research", "standard")

    assert output.outline
    assert output.research_questions


def test_writer_and_verifier_keep_sourced_claim_exportable():
    draft = ReportWriterAgent(FakeRouter()).write(
        WriterInput(job_id="job-1", section_title="Summary", evidence=["Evidence text"])
    )
    verified = VerifierAgent(FakeRouter()).verify(draft.claims)

    assert not verified.blockers
    assert verified.claims[0].source_ids


def test_planner_agent_accepts_mocked_gemini_json_style_response():
    router = Mock()
    router.get_model.return_value = RoutedModel(provider="gemini", model_name="gemini-1.5-flash")

    output = PlannerAgent(router).plan("AI reporting", "technical_report", "deep")

    assert "Executive Summary" in output.outline
    assert output.research_questions
