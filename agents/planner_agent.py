"""Planner agent for report outlines."""

from json import JSONDecodeError

from app.logging_config import get_logger
from schemas.agent_outputs import PlannerOutput
from schemas.reports import ReportDepth, ReportJob
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)

DEPTH_SECTION_RANGES = {
    ReportDepth.BRIEF: (2, 3),
    ReportDepth.STANDARD: (5, 7),
    ReportDepth.DEEP: (8, 12),
}
DEPTH_WORD_COUNTS = {
    ReportDepth.BRIEF: 1200,
    ReportDepth.STANDARD: 3500,
    ReportDepth.DEEP: 8000,
}


class PlannerAgent:
    """Create report outlines and research questions."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize planner with model router."""
        self.router = router or ModelRouter()
        self.sys_prompt = (
            "You are ReportForge PlannerAgent. Return JSON only, with no markdown fences. "
            "The JSON must validate PlannerOutput: outline, research_questions, target_word_count. "
            "Section counts must match ReportDepth: Brief=2-3, Standard=5-7, Deep=8-12. "
            "Research questions must be specific, answerable, and evidence-oriented."
        )
        self.model = CostTrackingModel(self.router.get_model())

    def plan(self, topic: str, report_type: str, depth: str) -> PlannerOutput:
        """Plan a report from primitive inputs."""
        job = ReportJob(
            id="planning-preview",
            topic=topic,
            type=report_type,
            depth=depth,
            created_at="1970-01-01T00:00:00+00:00",
        )
        return self.run(job)

    def run(self, job: ReportJob) -> PlannerOutput:
        """Return a validated PlannerOutput for a report job."""
        logger.info("planner_started", job_id=job.id, report_type=job.type.value, depth=job.depth.value)
        prompt = self._build_prompt(job)
        raw_response = self.model(prompt).text
        try:
            output = self._parse_output(raw_response)
        except (JSONDecodeError, ValueError):
            correction_prompt = f"{prompt}\nReturn only corrected JSON for PlannerOutput."
            logger.warning("planner_parse_failed", job_id=job.id)
            corrected = self.model(correction_prompt).text
            output = self._parse_output(corrected, fallback_job=job)
        output = self._enforce_depth_limits(output, job.depth)
        logger.info(
            "planner_completed",
            job_id=job.id,
            sections=len(output.outline),
            target_word_count=output.target_word_count,
        )
        return output

    def _build_prompt(self, job: ReportJob) -> str:
        """Build the JSON-only planner prompt."""
        min_sections, max_sections = DEPTH_SECTION_RANGES[job.depth]
        return (
            f"{self.sys_prompt}\n"
            f"Topic: {job.topic}\n"
            f"Report type: {job.type.value}\n"
            f"Depth: {job.depth.value}\n"
            f"Required section count: {min_sections}-{max_sections}\n"
            f"Target word count: {DEPTH_WORD_COUNTS[job.depth]}\n"
        )

    @staticmethod
    def _parse_output(raw_response: str, fallback_job: ReportJob | None = None) -> PlannerOutput:
        """Parse model JSON or produce deterministic free-tier fallback output."""
        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start >= 0 and end > start:
            return PlannerOutput.model_validate_json(raw_response[start : end + 1])
        if fallback_job is None:
            raise JSONDecodeError("Planner response did not contain JSON", raw_response, 0)
        return PlannerAgent._fallback_output(fallback_job)

    @staticmethod
    def _fallback_output(job: ReportJob) -> PlannerOutput:
        """Create a deterministic schema-valid plan when the local model is a stub."""
        min_sections, _max_sections = DEPTH_SECTION_RANGES[job.depth]
        base = [
            "Executive Summary",
            "Context and Scope",
            "Evidence Review",
            "Analysis",
            "Risks and Limitations",
            "Recommendations",
            "Appendix and Bibliography",
            "Implementation Considerations",
        ]
        outline = base[:min_sections]
        return PlannerOutput(
            outline=outline,
            research_questions=[
                f"What recent evidence directly supports the core claims about {job.topic}?",
                f"Which measurable risks or constraints affect a {job.type.value} report on {job.topic}?",
                f"What sources provide the strongest contrary or qualifying evidence for {job.topic}?",
            ],
            target_word_count=DEPTH_WORD_COUNTS[job.depth],
        )

    @staticmethod
    def _enforce_depth_limits(output: PlannerOutput, depth: ReportDepth) -> PlannerOutput:
        """Normalize section count and target words to depth constraints."""
        min_sections, max_sections = DEPTH_SECTION_RANGES[depth]
        outline = output.outline[:max_sections]
        while len(outline) < min_sections:
            outline.append(f"Additional Evidence Section {len(outline) + 1}")
        return output.model_copy(
            update={"outline": outline, "target_word_count": DEPTH_WORD_COUNTS[depth]}
        )
