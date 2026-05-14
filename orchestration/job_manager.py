"""Report job queue, status management, and in-process MVP execution."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import get_settings
from app.database import AgentTraceRecord, ReportJobRecord, SessionLocal
from app.logging_config import get_logger
from agents.planner_agent import PlannerAgent
from agents.research_agent import ResearchAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from schemas.api import CreateJobRequest, CreateJobResponse, JobProgress
from schemas.agent_outputs import WriterInput
from schemas.costs import AgentTrace, CostMetrics
from schemas.reports import ReportJob, ReportSection, ReportStatus
from schemas.sources import Source
from tools.export.markdown import render_markdown
from orchestration.hitl import requires_approval

logger = get_logger(__name__)


class JobManager:
    """In-memory MVP job manager with SQLite trace/job persistence."""

    def __init__(self) -> None:
        """Initialize empty job manager."""
        self.jobs: dict[str, ReportJob] = {}
        self.sources_by_job: dict[str, list[Source]] = {}
        self.traces_by_job: dict[str, list[AgentTrace]] = {}
        self.progress_by_job: dict[str, JobProgress] = {}
        self.urls_by_job: dict[str, list[str]] = {}

    def create_job(self, request: CreateJobRequest, *, session_id: str = "anonymous") -> CreateJobResponse:
        """Create a pending report job."""
        job_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        job = ReportJob(
            id=job_id,
            topic=request.topic,
            type=request.type,
            depth=request.depth,
            status=ReportStatus.PENDING,
            created_at=created_at,
            session_id=session_id,
        )
        self.jobs[job_id] = job
        self.sources_by_job[job_id] = []
        self.traces_by_job[job_id] = []
        self.urls_by_job[job_id] = request.urls
        self.progress_by_job[job_id] = JobProgress(job_id=job_id, status=job.status, current_step="queued")
        with SessionLocal() as session:
            session.merge(
                ReportJobRecord(
                    id=job.id,
                    session_id=job.session_id,
                    topic=job.topic,
                    type=job.type.value,
                    depth=job.depth.value,
                    status=job.status.value,
                    cost=float(job.cost.estimated_cost_usd),
                    created_at=created_at,
                    completed_at=None,
                )
            )
            session.commit()
        logger.info("job_created", job_id=job_id, topic=request.topic, report_type=request.type.value)
        return CreateJobResponse(job_id=job_id, status=job.status)

    def progress(self, job_id: str) -> JobProgress:
        """Return progress for a job."""
        return self.progress_by_job[job_id]

    def get_job(self, job_id: str) -> ReportJob:
        """Return a full job snapshot."""
        return self.jobs[job_id]

    def list_sources(self, job_id: str) -> list[Source]:
        """Return all sources for a job."""
        return self.sources_by_job[job_id]

    def list_sections(self, job_id: str) -> list[ReportSection]:
        """Return all report sections for a job."""
        return self.jobs[job_id].sections

    def list_traces(self, job_id: str) -> list[AgentTrace]:
        """Return all execution traces for a job."""
        return self.traces_by_job[job_id]

    def run_job(self, job_id: str) -> None:
        """Run the zero-cost MVP report workflow for an accepted job."""
        job = self.jobs[job_id]
        try:
            self._set_progress(job_id, ReportStatus.RUNNING, "PlannerAgent", "planning outline", 10.0)
            planner_output = PlannerAgent().plan(job.topic, job.type.value, job.depth.value)
            self._append_trace(job_id, "PlannerAgent", job.topic, planner_output.model_dump_json())

            self._set_progress(job_id, ReportStatus.RUNNING, "ResearchAgent", "collecting sources", 30.0)
            research_output = ResearchAgent().research(job_id, job.topic, self.urls_by_job.get(job_id, []))
            self.sources_by_job[job_id] = research_output.sources
            self._append_trace(job_id, "ResearchAgent", job.topic, research_output.model_dump_json())

            evidence = [source.raw_text for source in research_output.sources]
            source_ids = [source.id for source in research_output.sources]
            first_section = planner_output.outline[0] if planner_output.outline else "Executive Summary"
            self._set_progress(job_id, ReportStatus.RUNNING, "ReportWriterAgent", "drafting first section", 55.0)
            writer_output = ReportWriterAgent().write(
                WriterInput(job_id=job_id, section_title=first_section, evidence=evidence)
            )
            claims = [
                claim.model_copy(update={"section_id": f"{job_id}-section-1", "source_ids": source_ids})
                for claim in writer_output.claims
            ]
            self._append_trace(job_id, "ReportWriterAgent", first_section, writer_output.model_dump_json())

            self._set_progress(job_id, ReportStatus.RUNNING, "VerifierAgent", "checking citations", 75.0)
            draft_section = ReportSection(
                id=f"{job_id}-section-1",
                job_id=job_id,
                title=writer_output.section_title,
                content=writer_output.content,
                order=0,
                status="drafted",
                sources=source_ids,
                claims=claims,
            )
            verifier_output = VerifierAgent().run(draft_section, research_output.sources)
            self._append_trace(job_id, "VerifierAgent", f"{len(claims)} claims", verifier_output.model_dump_json())

            section_status = "blocked" if verifier_output.blockers else "drafted"
            section = draft_section.model_copy(
                update={"status": section_status, "claims": verifier_output.claims}
            )
            final_status = self._final_status(job, has_blockers=bool(verifier_output.blockers))
            job.sections = [section]
            job.status = final_status
            job.completed_at = None if final_status == ReportStatus.AWAITING_APPROVAL else datetime.now(timezone.utc).isoformat()
            self._set_progress(job_id, final_status, None, final_status.value, 100.0, cost=job.cost)
            self._persist_job(job)
            logger.info("job_completed", job_id=job_id, status=job.status.value)
        except Exception as exc:
            logger.exception("job_failed", job_id=job_id, error=str(exc))
            job.status = ReportStatus.FAILED
            self._set_progress(job_id, ReportStatus.FAILED, None, str(exc), 100.0)
            self._persist_job(job)

    def execute(self, job_id: str) -> None:
        """Background task entrypoint for FastAPI."""
        self.run_job(job_id)

    def regenerate_section(self, job_id: str, section_id: str, feedback: str) -> ReportSection:
        """Apply a section-level regeneration marker and keep the report traceable."""
        for index, section in enumerate(self.jobs[job_id].sections):
            if section.id == section_id:
                updated = section.model_copy(
                    update={
                        "content": f"{section.content}\n\nReviewer feedback addressed: {feedback}".strip(),
                        "status": "regenerated",
                    }
                )
                self.jobs[job_id].sections[index] = updated
                self._append_trace(job_id, "SectionRegenerator", feedback, updated.model_dump_json())
                return updated
        raise KeyError(section_id)

    def approve(self, job_id: str) -> ReportJob:
        """Approve a HITL-gated report and mark it completed."""
        job = self.jobs[job_id]
        job.status = ReportStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._set_progress(job_id, ReportStatus.COMPLETED, None, "approved", 100.0)
        self._persist_job(job)
        return job

    def retry(self, job_id: str) -> None:
        """Retry a failed job from the current in-memory checkpoint."""
        self.run_job(job_id)

    def export_markdown(self, job_id: str) -> str:
        """Render a Markdown export for a completed or approved report."""
        job = self.jobs[job_id]
        blockers = [claim.id for section in job.sections for claim in section.claims if claim.blocks_export]
        if blockers:
            raise ValueError(f"export blocked by unsupported claims: {', '.join(blockers)}")
        sections = [section.content for section in job.sections]
        bibliography = [
            f"{source.citation_key} {source.title}" + (f" - {source.url}" if source.url else "")
            for source in self.sources_by_job[job_id]
        ]
        return render_markdown(job.topic, sections, bibliography)

    def cost_summary(self) -> dict[str, float | int]:
        """Return aggregate zero-cost testing metrics."""
        total_tokens = sum(trace.tokens for traces in self.traces_by_job.values() for trace in traces)
        estimated_kimi = sum(
            float(trace.estimated_kimi_cost_usd) for traces in self.traces_by_job.values() for trace in traces
        )
        return {
            "job_count": len(self.jobs),
            "total_tokens": total_tokens,
            "actual_cost_usd": 0.0,
            "estimated_kimi_cost_usd": estimated_kimi,
        }

    def _set_progress(
        self,
        job_id: str,
        status: ReportStatus,
        active_agent: str | None,
        current_step: str,
        percent_complete: float,
        *,
        cost: CostMetrics | None = None,
    ) -> None:
        """Update job status and progress atomically for the in-memory MVP."""
        self.jobs[job_id].status = status
        self.progress_by_job[job_id] = JobProgress(
            job_id=job_id,
            status=status,
            active_agent=active_agent,
            current_step=current_step,
            percent_complete=percent_complete,
            cost=cost or self.jobs[job_id].cost,
        )

    def _append_trace(self, job_id: str, agent_name: str, input_text: str, output_text: str) -> None:
        """Append an execution trace to memory and SQLite."""
        token_count = len(input_text.split()) + len(output_text.split())
        estimated_kimi = Decimal(token_count) * Decimal("0.000002")
        trace = AgentTrace(
            id=str(uuid4()),
            job_id=job_id,
            agent_name=agent_name,
            input=input_text,
            output=output_text,
            tokens=token_count,
            estimated_kimi_cost_usd=estimated_kimi,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.traces_by_job[job_id].append(trace)
        self.jobs[job_id].cost = self._rollup_cost(job_id)
        with SessionLocal() as session:
            session.add(
                AgentTraceRecord(
                    id=trace.id,
                    job_id=trace.job_id,
                    agent_name=trace.agent_name,
                    input=trace.input,
                    output=trace.output,
                    tokens=trace.tokens,
                    cost=float(trace.cost),
                    estimated_kimi_cost_usd=float(trace.estimated_kimi_cost_usd),
                    latency=trace.latency_ms,
                    retry_attempt=trace.retry_attempt,
                    created_at=trace.timestamp,
                )
            )
            session.commit()

    def _rollup_cost(self, job_id: str) -> CostMetrics:
        """Aggregate per-trace token and estimated cost metrics for a job."""
        traces = self.traces_by_job[job_id]
        total_tokens = sum(trace.tokens for trace in traces)
        estimated_kimi = sum((trace.estimated_kimi_cost_usd for trace in traces), Decimal("0.00"))
        return CostMetrics(
            prompt_tokens=total_tokens,
            completion_tokens=0,
            estimated_cost_usd=Decimal("0.00"),
            estimated_kimi_cost_usd=estimated_kimi,
            model_name=get_settings().gemini_model_name,
        )

    def _persist_job(self, job: ReportJob) -> None:
        """Persist the current job lifecycle state to SQLite."""
        with SessionLocal() as session:
            record = session.get(ReportJobRecord, job.id)
            if record is not None:
                record.status = job.status.value
                record.cost = float(job.cost.estimated_cost_usd)
                record.completed_at = job.completed_at
            session.commit()

    @staticmethod
    def _final_status(job: ReportJob, *, has_blockers: bool) -> ReportStatus:
        """Resolve final job status from verification and HITL rules."""
        if has_blockers:
            return ReportStatus.FAILED
        if requires_approval(job.type, job.depth):
            return ReportStatus.AWAITING_APPROVAL
        return ReportStatus.COMPLETED
