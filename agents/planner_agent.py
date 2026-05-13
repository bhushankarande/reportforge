"""Planner agent for report outlines."""

from schemas.agent_outputs import PlannerOutput
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter


class PlannerAgent:
    """Create report outlines and research questions."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize planner with model router."""
        self.router = router or ModelRouter()

    def plan(self, topic: str, report_type: str, depth: str) -> PlannerOutput:
        """Return a deterministic outline for the requested report."""
        tracked_model = CostTrackingModel(self.router.get_model("gemini"))
        tracked_model(f"Plan {depth} {report_type} report for {topic}")
        outline = ["Executive Summary", "Key Findings", "Evidence Review", "Recommendations"]
        if depth == "deep":
            outline.insert(2, "Market and Technical Context")
        return PlannerOutput(
            outline=outline,
            research_questions=[
                f"What is the current state of {topic}?",
                f"What evidence matters for a {report_type} report?",
            ],
        )
