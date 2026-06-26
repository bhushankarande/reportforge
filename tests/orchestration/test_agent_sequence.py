from agents.critic_agent import CriticInput
from orchestration.job_manager import ReportPipeline
from schemas.agent_outputs import (
    CriticOutput,
    PlannerOutput,
    ResearchOutput,
    VerifierOutput,
    WriterOutput,
)
from schemas.reports import ReportDepth, ReportJob, ReportStatus, ReportType
from schemas.sources import Claim, Source


def test_report_pipeline_runs_explicit_live_agent_sequence(monkeypatch):
    calls: list[str] = []
    verifier_outputs: list[VerifierOutput] = []

    class FakeRouter:
        pass

    class FakePlanner:
        def __init__(self, router):
            self.router = router

        def run(self, job):
            calls.append("PlannerAgent")
            return PlannerOutput(
                outline=["Executive Summary"],
                research_questions=["What evidence supports adoption?"],
                target_word_count=500,
            )

        def section_plan_for_writer(self, section_title):
            return '{"section_plan":{"research_questions":["What evidence supports adoption?"]}}'

    class FakeRetriever:
        def retrieve(self, query, filters=None, *, limit=10):
            calls.append("Evidence/RAG")
            return [
                type(
                    "Hit",
                    (),
                    {
                        "source_id": "job-1-web-source-1",
                        "text": "Robotics adoption evidence supports planning workflows.",
                    },
                )()
            ]

    class FakeResearch:
        def __init__(self, router):
            self.last_retriever = FakeRetriever()

        def research(self, job_id, topic, urls):
            source = Source(
                id=f"{job_id}-web-source-1",
                job_id=job_id,
                title="Robotics Source",
                url="https://example.com/report",
                raw_text="Robotics adoption evidence supports planning workflows.",
                citation_key="[Web1]",
            )
            return ResearchOutput(sources=[source])

    class FakeWriter:
        def __init__(self, router):
            pass

        def write(self, writer_input):
            calls.append("ReportWriterAgent")
            assert "Robotics adoption evidence" in writer_input.evidence[0]
            return WriterOutput(
                section_title=writer_input.section_title,
                content="## Executive Summary\n\nRobotics adoption evidence supports planning workflows. [Web1]",
                claims=[
                    Claim(
                        id="claim-1",
                        section_id="pending",
                        text="Robotics adoption evidence supports planning workflows. [Web1]",
                        source_ids=["Web1"],
                    )
                ],
                sources_used=["Web1"],
            )

    class FakeVerifier:
        def __init__(self, router, *, use_llm=True):
            pass

        def run(self, section, sources):
            calls.append("VerifierAgent")
            output = VerifierOutput(claims=section.claims, blockers=[], warnings=[])
            verifier_outputs.append(output)
            return output

    class FakeCritic:
        def __init__(self, router, *, use_llm=True):
            assert use_llm is False

        def run(self, critic_input: CriticInput):
            calls.append("CriticAgent")
            assert critic_input.sources
            assert critic_input.verifier_results == verifier_outputs
            return CriticOutput(quality_score=0.9, fixes=[])

    monkeypatch.setattr("orchestration.job_manager.ModelRouter", lambda settings: FakeRouter())
    monkeypatch.setattr("orchestration.job_manager.PlannerAgent", FakePlanner)
    monkeypatch.setattr("orchestration.job_manager.ResearchAgent", FakeResearch)
    monkeypatch.setattr("orchestration.job_manager.ReportWriterAgent", FakeWriter)
    monkeypatch.setattr("orchestration.job_manager.VerifierAgent", FakeVerifier)
    monkeypatch.setattr("orchestration.job_manager.CriticAgent", FakeCritic)

    job = ReportJob(
        id="job-1",
        topic="Robotics adoption",
        type=ReportType.MARKET_RESEARCH,
        depth=ReportDepth.STANDARD,
        created_at="2026-01-01T00:00:00+00:00",
    )
    traces: list[str] = []
    progress: list[str | None] = []

    result = ReportPipeline().run(
        job=job,
        urls=["https://example.com/report"],
        provider="gemini",
        set_progress=lambda status, active_agent, step, percent: progress.append(active_agent),
        append_trace=lambda agent_name, input_text, output_text: traces.append(agent_name),
    )

    assert calls == [
        "PlannerAgent",
        "Evidence/RAG",
        "ReportWriterAgent",
        "VerifierAgent",
        "CriticAgent",
    ]
    assert traces == [
        "PlannerAgent",
        "EvidenceRAG",
        "ReportWriterAgent",
        "VerifierAgent",
        "CriticAgent",
    ]
    assert progress[-1] == "CriticAgent"
    assert result.status == ReportStatus.COMPLETED
