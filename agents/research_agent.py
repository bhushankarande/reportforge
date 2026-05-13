"""Research agent using mock search for MVP."""

from schemas.agent_outputs import ResearchOutput
from schemas.sources import Source
from tools.llm.model_router import ModelRouter


class ResearchAgent:
    """Collect external sources with metadata and relevance scores."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize research agent."""
        self.router = router or ModelRouter()

    def research(self, job_id: str, topic: str) -> ResearchOutput:
        """Return deterministic mock sources for zero-cost testing."""
        self.router.get_model("gemini")
        source = Source(
            id=f"{job_id}-mock-source-1",
            job_id=job_id,
            title=f"Mock research source for {topic}",
            summary=f"Mock source summary about {topic}.",
            relevance_score=0.85,
            raw_text=f"{topic} has relevant market and technical evidence.",
            citation_key="[Mock2026]",
        )
        return ResearchOutput(sources=[source])
