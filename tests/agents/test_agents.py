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
            '{"section_title":"Summary","content":"Generated analysis grounded in evidence '
            'shows that robotics systems can use large language models to translate user intent '
            'into autonomous task planning workflows. [Web1] The same evidence supports human-robot '
            'collaboration because language-driven interfaces can reduce the gap between operator '
            'instructions and robot execution in practical settings. [Web1] These capabilities make '
            'LLM-powered robotics relevant for report analysis because they connect planning, control, '
            'and collaboration in one evidence-backed workflow. [Web1]","claims":["Generated analysis '
            'grounded in evidence."],"sources_used":["Web1"]}'
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
        WriterInput(
            job_id="job-1",
            section_title="Summary",
            evidence=[
                (
                    "Robotics systems can use large language models to translate human instructions "
                    "into task plans for autonomous execution. [Web1]"
                )
            ],
        )
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


def test_writer_repairs_uncited_model_sentences_and_maps_claim_sources():
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

    assert "Unsupported broad market claim without citation. [Web1]" in draft.content
    assert draft.claims[0].source_ids == ["Web1"]
    assert draft.claims[-1].source_ids == ["Web2"]


def test_writer_expands_terse_model_output_to_paragraphs():
    class TerseModel:
        provider = "gemini"
        model_name = "gemini-test"

        def __call__(self, prompt):
            return '{"content":"Short supported line. [Web1]"}'

    class TerseRouter:
        def get_model(self, provider=None):
            return TerseModel()

    evidence = [
        (
            "Large language models can help users control drones, robot arms, and home assistant "
            "robots through natural language instructions. The same evidence describes robotics "
            "interfaces that translate user goals into executable robot behavior for collaborative "
            "settings and autonomous task planning. [Web1]"
        )
    ]

    draft = ReportWriterAgent(TerseRouter()).write(
        WriterInput(job_id="job-1", section_title="Executive Summary", evidence=evidence)
    )
    body = draft.content.split("\n\n", 1)[1]

    assert len(body.split()) >= 45
    assert "[Web1]" in draft.content
    assert "available evidence states" not in draft.content


def test_writer_fallback_filters_boilerplate_and_synthesizes_paragraphs():
    class TerseModel:
        provider = "gemini"
        model_name = "gemini-test"

        def __call__(self, prompt):
            return '{"content":"Too short. [Web1]"}'

    class TerseRouter:
        def get_model(self, provider=None):
            return TerseModel()

    evidence = [
        (
            "Control a robot with natural language commands using LLM and control components. "
            "The approach translates operator instructions into precise robotic actions for task execution. "
            "REQUEST A QUOTE Products in Interest Linear Inverted Pendulum Smart Motion Devices "
            "Mobile Autonomous Robot Want to hear more from us?. [Web1]"
        ),
        (
            "Large language models can provide tools for controlling robots through natural language, "
            "letting the model decide how to send appropriate commands to the robot. [Web2]"
        ),
    ]

    draft = ReportWriterAgent(TerseRouter()).write(
        WriterInput(job_id="job-1", section_title="Market Analysis", evidence=evidence)
    )

    assert "REQUEST A QUOTE" not in draft.content
    assert "Products in Interest" not in draft.content
    assert "available evidence states" not in draft.content
    assert "From a market perspective" in draft.content
    assert len(draft.content.split("\n\n")) >= 3


def test_research_excerpt_filters_scraped_page_chrome():
    text = (
        "REQUEST A QUOTE Products in Interest Linear Inverted Pendulum Smart Motion Devices. "
        "Large language models help robots interpret natural language instructions and convert "
        "them into task plans for autonomous execution. "
        "Want to hear more from us? Subscribe to our newsletter. "
        "Robotics systems can use language models to improve human-robot collaboration in "
        "settings where operators describe goals instead of low-level commands."
    )

    excerpt = ResearchAgent._topic_excerpt(text, "robotics powered by llms")

    assert "REQUEST A QUOTE" not in excerpt
    assert "Products in Interest" not in excerpt
    assert "natural language instructions" in excerpt


def test_planner_agent_accepts_mocked_gemini_json_style_response():
    router = Mock()
    router.get_model.return_value = RoutedModel(provider="gemini", model_name="gemini-1.5-flash")

    output = PlannerAgent(router).plan("AI reporting", "technical_report", "deep")

    assert "Executive Summary" in output.outline
    assert output.research_questions


def test_planner_agent_normalizes_object_based_local_model_json():
    payload = (
        '{"outline":[{"section_title":"Executive Summary"},{"title":"Market Overview"}],'
        '"research_questions":[{"question":"What evidence supports adoption?"}],'
        '"target_word_count":1200}'
    )

    output = PlannerAgent._parse_output(payload)

    assert output.outline == ["Executive Summary", "Market Overview"]
    assert output.research_questions == ["What evidence supports adoption?"]


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
