from agents.document_reader_agent import DocumentReaderAgent
from agents.research_agent import ResearchAgent
from tools.rag.evidence_pipeline import EvidencePipeline, RawEvidence


class FakeRouter:
    def get_model(self, provider=None):
        return None


def test_evidence_pipeline_normalizes_web_and_upload_sources():
    result = EvidencePipeline("job-1", chunk_size=120, overlap=0).ingest(
        [
            RawEvidence(
                source_type="web",
                title="Robotics Research",
                url="https://example.com/report",
                text=(
                    "Robotics teams use language models for planning, controls, and execution. "
                    "The same robotics evidence describes collaborative operators and safe control."
                ),
                summary="Robotics teams use language models.",
                relevance_score=0.8,
                citation_key="[Example1]",
            ),
            RawEvidence(
                source_type="upload",
                title="notes.md",
                text=(
                    "Uploaded notes describe robotics deployment risks, retrieval evidence, "
                    "and safety checks for report planning."
                ),
            ),
        ]
    )

    assert [source.id for source in result.sources] == [
        "job-1-web-source-1",
        "job-1-upload-source-1",
    ]
    assert result.sources[0].url == "https://example.com/report"
    assert result.sources[1].url is None
    assert result.sources[1].citation_key == "[Upload1]"
    assert {chunk.source_id for chunk in result.chunks} == {
        "job-1-web-source-1",
        "job-1-upload-source-1",
    }

    upload_hits = result.retriever.retrieve("deployment risks", filters={"source_type": "upload"})

    assert upload_hits
    assert all(hit.source_type == "upload" for hit in upload_hits)
    assert upload_hits[0].id in {chunk.id for chunk in result.chunks}


def test_document_reader_can_return_uploaded_evidence(tmp_path):
    path = tmp_path / "market-notes.md"
    path.write_text(
        (
            "The uploaded market notes describe AI report generation, retrieval evidence, "
            "and source-grounded planning for executive summaries. "
        )
        * 3,
        encoding="utf-8",
    )

    output = DocumentReaderAgent().read([str(path)])
    result = DocumentReaderAgent().read_evidence("job-2", [str(path)])

    assert output.source_ids == ["market-notes"]
    assert output.chunks_indexed == 1
    assert result.sources[0].id == "job-2-upload-source-1"
    assert result.sources[0].title == "market-notes.md"
    assert result.chunks
    assert result.retriever.retrieve("executive summaries", filters={"source_type": "upload"})


def test_research_agent_indexes_url_evidence(monkeypatch):
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

    agent = ResearchAgent(FakeRouter())
    output = agent.research("job-3", "robotics", ["https://example.com?utm_source=test"])

    assert output.sources[0].url == "https://example.com/"
    assert agent.last_evidence_chunks
    assert agent.last_retriever is not None
    hits = agent.last_retriever.retrieve("robotics planning", filters={"source_type": "web"})
    assert hits
    assert all(hit.source_id == output.sources[0].id for hit in hits)
