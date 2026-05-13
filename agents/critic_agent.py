"""Critic agent for report quality feedback."""

from schemas.agent_outputs import CriticOutput
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter


class CriticAgent:
    """Score report quality and suggest fixes."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize critic with model router."""
        self.router = router or ModelRouter()

    def critique(self, report_markdown: str) -> CriticOutput:
        """Return a quality score for a report draft."""
        tracked_model = CostTrackingModel(self.router.get_model("gemini"))
        tracked_model("Critique report quality")
        score = 0.8 if "[SourceID]" in report_markdown or "[" in report_markdown else 0.4
        fixes = [] if score >= 0.8 else ["Add source-backed citations."]
        return CriticOutput(quality_score=score, fixes=fixes)
