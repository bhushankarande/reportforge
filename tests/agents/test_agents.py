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
            '{"section_title":"Summary","paragraphs":["Generated analysis grounded in evidence '
            'shows that robotics systems can use large language models to translate user intent '
            'into autonomous task planning workflows. [Web1] The same evidence supports human-robot '
            'collaboration because language-driven interfaces can reduce the gap between operator '
            'instructions and robot execution in practical settings. [Web1] These capabilities make '
            'LLM-powered robotics relevant for report analysis because they connect planning, control, '
            'and collaboration in one evidence-backed workflow. [Web1]"],"claims":["Generated analysis '
            'grounded in evidence."],"sources_used":["Web1"]}'
        )


class JsonWriterRouter:
    def get_model(self, provider=None):
        return JsonWriterModel()


class ContradictingVerifierModel:
    provider = "gemini"
    model_name = "llama3.1:8b"

    def __call__(self, prompt):
        return '{"verification_status":"CONTRADICTED","confidence":1.0,"reason":"incorrect model override"}'


class ContradictingVerifierRouter:
    def get_model(self, provider=None):
        return ContradictingVerifierModel()


class OllamaVerifierModel(ContradictingVerifierModel):
    provider = "ollama"


class OllamaVerifierRouter:
    def get_model(self, provider=None):
        return OllamaVerifierModel()


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
    evidence = (
        "Generated analysis grounded in evidence shows that robotics systems can use large "
        "language models to translate user intent into autonomous task planning workflows. "
        "The same evidence supports human-robot collaboration because language-driven "
        "interfaces can reduce the gap between operator instructions and robot execution in "
        "practical settings. These capabilities make LLM-powered robotics relevant for report "
        "analysis because they connect planning, control, and collaboration in one "
        "evidence-backed workflow. [Web1]"
    )
    draft = ReportWriterAgent(JsonWriterRouter()).write(
        WriterInput(
            job_id="job-1",
            section_title="Summary",
            evidence=[evidence],
        )
    )

    assert "Generated analysis grounded in evidence" in draft.content
    assert draft.sources_used == ["Web1"]


def test_writer_does_not_repair_uncited_model_sentences():
    class MixedCitationModel:
        provider = "gemini"
        model_name = "gemini-test"

        def __call__(self, prompt):
            return (
                '{"paragraphs":["Robotics systems can translate language goals into robot plans. [Web1] '
                'Unsupported broad market claim without citation. '
                'Language interfaces can connect operator instructions to robot execution. [Web2]"]}'
            )

    class MixedCitationRouter:
        def get_model(self, provider=None):
            return MixedCitationModel()

    draft = ReportWriterAgent(MixedCitationRouter()).write(
        WriterInput(
            job_id="job-1",
            section_title="Summary",
            evidence=[
                "Robotics systems can translate language goals into robot plans. [Web1]",
                "Language interfaces can connect operator instructions to robot execution. [Web2]",
            ],
        )
    )

    assert "Unsupported broad market claim" not in draft.content
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

    assert len(body.split()) >= 35
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
    assert len(draft.content.split("\n\n")) >= 3


def test_writer_fallback_respects_section_word_target():
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
            "AI shopping agents are changing consumer behavior by moving product discovery "
            "from keyword search into conversational decision support. Consumers can describe "
            "preferences, budgets, constraints, and purchase timing in natural language while "
            "the assistant narrows options and compares tradeoffs. Retailers face a shift in "
            "where influence happens because the agent can mediate product visibility, choice, "
            "and checkout steps before a shopper reaches a retailer website. The same evidence "
            "shows that trust, transparency, and data quality shape whether consumers accept "
            "recommendations from AI shopping assistants. [Web1]"
        ),
        (
            "Retailers using agentic commerce need AI-ready product content, reliable pricing, "
            "inventory availability, and clear policies for data use because AI assistants rely "
            "on structured signals when presenting options. Brand-owned assistants can preserve "
            "direct customer relationships by capturing preference data and explaining why a "
            "recommendation fits the shopper's needs. Third-party assistants may increase "
            "convenience but can also weaken brand loyalty if consumers delegate comparison and "
            "purchase decisions to neutral intermediaries. [Web2]"
        ),
        (
            "Consumer response depends on whether the shopping agent reduces friction without "
            "making the experience feel opaque. Useful agents ask clarifying questions, remember "
            "constraints, compare relevant products, and surface evidence such as reviews, price, "
            "delivery timing, and return policies. Poorly explained recommendations can reduce "
            "confidence because shoppers may suspect hidden sponsorship, stale inventory, or "
            "misaligned incentives. [Web3]"
        ),
    ]
    section_plan = '{"section_plan":{"target_words":420,"research_questions":["How do consumers respond to AI shopping agents?"]}}'

    draft = ReportWriterAgent(TerseRouter()).write(
        WriterInput(
            job_id="job-1",
            section_title="Consumer Response",
            evidence=evidence,
            rolling_summary=section_plan,
        )
    )
    body = draft.content.split("\n\n", 1)[1]

    assert len(body.split()) >= 200
    assert "[Web1]" in draft.content
    assert "[Web2]" in draft.content


def test_writer_does_not_extract_citation_only_claims():
    content = "## Sources\n\n[Web3]\n\n[Web1]\n\n[Web2]\n\n[Web4]"

    claims = ReportWriterAgent._extract_claims("job-1", "Sources", content, ["Web1", "Web2"])

    assert claims[0].text == "No verifiable claim could be extracted from this section."
    assert claims[0].verification_status == VerificationStatus.UNVERIFIED


def test_research_excerpt_filters_scraped_page_chrome():
    text = (
        "REQUEST A QUOTE Products in Interest Linear Inverted Pendulum Smart Motion Devices. "
        "Large language models help robots interpret natural language instructions and convert "
        "them into task plans for autonomous execution. "
        "Want to hear more from us? Subscribe to our newsletter. "
        "Robotics systems can use language models to improve human-robot collaboration in "
        "settings where operators describe goals instead of low-level commands."
    )

    excerpt = ResearchAgent._topic_excerpt(
        text,
        ResearchAgent._topic_terms("robotics powered by llms"),
        max_chars=2_500,
    )

    assert "REQUEST A QUOTE" not in excerpt
    assert "Products in Interest" not in excerpt
    assert "language models" in excerpt


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
    assert "What evidence supports adoption?" in output.research_questions


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


def test_verifier_does_not_let_llm_contradict_strong_source_match():
    source = Source(
        id="source-1",
        job_id="job-1",
        title="Agentic commerce evidence",
        summary="AI shopping agents are changing commerce.",
        raw_text=(
            "The rise of AI shopping agents represents a seismic shift in how commerce "
            "will be conducted on a global scale and it is already underway."
        ),
        citation_key="[Bcg2]",
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
                text=(
                    "The rise of AI shopping agents represents a seismic shift in how commerce "
                    "will be conducted on a global scale and it is already underway. [Bcg2]"
                ),
                source_ids=["source-1"],
            )
        ],
    )

    output = VerifierAgent(ContradictingVerifierRouter()).run(section, [source])

    assert output.claims[0].verification_status == VerificationStatus.SUPPORTED
    assert not output.blockers


def test_verifier_ignores_numbers_inside_citation_keys():
    source = Source(
        id="source-1",
        job_id="job-1",
        title="Agentic commerce evidence",
        summary="AI shopping agents are changing commerce.",
        raw_text=(
            "The rise of AI shopping agents represents a seismic shift in how commerce "
            "will be conducted on a global scale and it is already underway."
        ),
        citation_key="[Bcg2]",
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
                text=(
                    "The rise of AI shopping agents represents a seismic shift in how commerce "
                    "will be conducted on a global scale and it is already underway. [Bcg2]"
                ),
                source_ids=["source-1"],
            )
        ],
    )

    output = VerifierAgent(FakeRouter(), use_llm=False).run(section, [source])

    assert output.claims[0].verification_status == VerificationStatus.SUPPORTED
    assert not output.blockers


def test_verifier_skips_llm_for_ollama_provider():
    verifier = VerifierAgent(OllamaVerifierRouter())

    assert verifier.use_llm is False


def test_research_agent_uses_url_sources(monkeypatch):
    def fake_fetch(url):
        return (
            "Robotics LLM Source",
            (
                "Robotics LLMs support task planning and collaboration by translating natural "
                "language goals into structured robot actions. Large language models can help "
                "operators describe objectives while robotic systems convert those objectives "
                "into plans, controls, and execution checks. This source discusses robotics, "
                "language models, planning, collaboration, autonomous execution, and control "
                "interfaces in enough detail to be useful evidence for a report. "
            )
            * 3,
        )

    monkeypatch.setattr("agents.research_agent.fetch_url_text", fake_fetch)

    output = ResearchAgent(FakeRouter()).research("job-1", "robotics", ["https://example.com"])

    assert output.sources[0].url == "https://example.com/"
    assert output.sources[0].citation_key == "[Example1]"
