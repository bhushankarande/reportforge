"""AgentScope-style workflow coordination."""

from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.research_agent import ResearchAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from orchestration.checkpoints import CheckpointStore
from orchestration.state import WorkflowState
from schemas.agent_outputs import WriterInput
from schemas.reports import ReportDepth, ReportType
from tools.llm.model_router import ModelRouter


class ReportWorkflow:
    """Coordinate agents without embedding agent business logic."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize workflow with shared router and checkpoints."""
        self.router = router or ModelRouter()
        self.checkpoints = CheckpointStore()

    def run(self, job_id: str, topic: str, report_type: ReportType, depth: ReportDepth) -> WorkflowState:
        """Run a minimal report workflow and checkpoint each step."""
        state = self.checkpoints.load(job_id) or WorkflowState(job_id=job_id)
        planner = PlannerAgent(self.router)
        research = ResearchAgent(self.router)
        writer = ReportWriterAgent(self.router)
        verifier = VerifierAgent(self.router)
        critic = CriticAgent(self.router)

        if "planned" not in state.completed_steps:
            plan = planner.plan(topic, report_type.value, depth.value)
            state.mark_completed("planned")
            self.checkpoints.save(state)
        else:
            plan = planner.plan(topic, report_type.value, depth.value)

        if "researched" not in state.completed_steps:
            research_output = research.research(job_id, topic)
            state.mark_completed("researched")
            self.checkpoints.save(state)
        else:
            research_output = research.research(job_id, topic)

        if "written" not in state.completed_steps:
            first_section = plan.outline[0]
            evidence = [source.raw_text for source in research_output.sources]
            draft = writer.write(WriterInput(job_id=job_id, section_title=first_section, evidence=evidence))
            verifier.verify(draft.claims)
            critic.critique(draft.content)
            state.mark_completed("written")
            self.checkpoints.save(state)
        return state
