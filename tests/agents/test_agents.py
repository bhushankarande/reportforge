from unittest.mock import Mock

from faker import Faker

from agents.planner_agent import PlannerAgent
from agents.research_agent import ResearchAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from schemas.agent_outputs import WriterInput
from schemas.reports import ReportDepth, ReportJob, ReportSection, ReportType
from schemas.sources import Claim, Source, VerificationStatus
from tools.llm.model_router import RoutedModel


fake = Faker()


class FakeRouter:
    def get_model(self, provider=None):
        return RoutedModel(provider=provider or "gemini", model_name="gemini-1.5-flash")


class JsonWriterModel:
    provider = "gemini"
    model_name = "gemini-test"

    def __call__(self, prompt):
        return (
            '{"section_title":"Summary","content":"Generated analysis grounded in evidence. '
            '[Web1]","claims":["Generated analysis grounded in evidence."],"sources_used":["Web1"]}'
        )


class JsonWriterRouter:
    def get_model(self, provider=None):
        return JsonWriterModel()


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


def test_writer_uses_model_generated_content_when_available():
    draft = ReportWriterAgent(JsonWriterRouter()).write(
        WriterInput(
            job_id="job-1",
            section_title="Summary",
            evidence=["Robotics evidence supports autonomous task planning. [Web1]"],
        )
    )

    assert "Generated analysis grounded in evidence" in draft.content
    assert draft.sources_used == ["Web1"]


def test_writer_prunes_uncited_model_sentences_and_maps_claim_sources():
    class MixedCitationModel:
        provider = "gemini"
        model_name = "gemini-test"

        def __call__(self, prompt):
            return (
                '{"content":"Supported robotics claim. [Web1] '
                'Unsupported broad market claim without citation. '
                'Second supported claim. [Web2]"}'
            )

    class MixedCitationRouter:
        def get_model(self, provider=None):
            return MixedCitationModel()

    draft = ReportWriterAgent(MixedCitationRouter()).write(
        WriterInput(
            job_id="job-1",
            section_title="Summary",
            evidence=["Robotics evidence. [Web1]", "More evidence. [Web2]"],
        )
    )

    assert "Unsupported broad market claim" not in draft.content
    assert draft.claims[0].source_ids == ["Web1"]
    assert draft.claims[1].source_ids == ["Web2"]


def test_planner_agent_accepts_mocked_gemini_json_style_response():
    router = Mock()
    router.get_model.return_value = RoutedModel(provider="gemini", model_name="gemini-1.5-flash")

    output = PlannerAgent(router).plan("AI reporting", "technical_report", "deep")

    assert "Executive Summary" in output.outline
    assert output.research_questions


def test_planner_agent_enforces_deep_section_count():
    job = ReportJob(
        id="job-1",
        topic="AI reporting",
        type=ReportType.TECHNICAL_REPORT,
        depth=ReportDepth.DEEP,
        created_at="2026-01-01T00:00:00+00:00",
    )

    output = PlannerAgent(FakeRouter()).run(job)

    assert 8 <= len(output.outline) <= 12
    assert output.target_word_count == 8000


def test_verifier_run_supports_claim_with_matching_source():
    source = Source(
        id="source-1",
        job_id="job-1",
        title="AI reporting evidence",
        summary="AI reporting has relevant market and technical evidence.",
        raw_text="AI reporting has relevant market and technical evidence.",
        citation_key="[Mock2026]",
    )
    section = ReportSection(
        id="section-1",
        job_id="job-1",
        title="Summary",
        order=0,
        claims=[
            Claim(
                id="claim-1",
                section_id="section-1",
                text="AI reporting has relevant market and technical evidence. [Mock2026]",
                source_ids=["source-1"],
                verification_status=VerificationStatus.UNVERIFIED,
            )
        ],
    )

    output = VerifierAgent(FakeRouter()).run(section, [source])

    assert output.claims[0].verification_status == VerificationStatus.SUPPORTED
    assert not output.blockers


def test_research_agent_uses_url_sources(monkeypatch):
    def fake_fetch(url):
        return "Robotics LLM Source", "Robotics LLMs support task planning and collaboration."

    monkeypatch.setattr("agents.research_agent.fetch_url_text", fake_fetch)

    output = ResearchAgent(FakeRouter()).research("job-1", "robotics", ["https://example.com"])

    assert output.sources[0].url == "https://example.com"
    assert output.sources[0].citation_key == "[Web1]"
