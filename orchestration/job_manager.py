"""Report job queue, status management, and in-process MVP execution."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import get_settings
from app.logging_config import get_logger
from app.services.report_store import ReportStore
from agents.critic_agent import CriticAgent, CriticInput
from agents.planner_agent import PlannerAgent
from agents.research_agent import ResearchAgent
from agents.verifier_agent import VerifierAgent
from agents.writer_agent import ReportWriterAgent
from schemas.api import CreateJobRequest, CreateJobResponse, JobProgress
from schemas.agent_outputs import VerifierOutput, WriterInput
from schemas.costs import AgentTrace, CostMetrics
from schemas.reports import ReportJob, ReportSection, ReportStatus
from schemas.sources import Source
from tools.llm.model_router import ModelRouter
from orchestration.hitl import requires_approval

logger = get_logger(__name__)

ProgressCallback = Callable[[ReportStatus, str | None, str, float], None]
TraceCallback = Callable[[str, str, str], None]


@dataclass(frozen=True)
class JobRunResult:
    """Result of one report pipeline execution."""

    status: ReportStatus
    sections: list[ReportSection]
    sources: list[Source]


class ReportPipeline:
    """Run the live planner/evidence/writer/verifier/critic report pipeline."""

    AGENT_SEQUENCE = (
        "PlannerAgent",
        "EvidenceRAG",
        "ReportWriterAgent",
        "VerifierAgent",
        "CriticAgent",
    )

    def run(
        self,
        *,
        job: ReportJob,
        urls: list[str],
        provider: str,
        set_progress: ProgressCallback,
        append_trace: TraceCallback,
    ) -> JobRunResult:
        """Execute the current report-generation pipeline."""
        router = ModelRouter(get_settings().model_copy(update={"active_llm_provider": provider}))

        set_progress(ReportStatus.RUNNING, "PlannerAgent", "planning outline", 10.0)
        planner = PlannerAgent(router)
        planner_output = planner.run(job)
        append_trace("PlannerAgent", job.topic, planner_output.model_dump_json())

        set_progress(ReportStatus.RUNNING, "EvidenceRAG", "collecting and indexing evidence", 30.0)
        research_agent = ResearchAgent(router)
        research_output = research_agent.research(job.id, job.topic, urls)
        sources = research_output.sources
        append_trace("EvidenceRAG", job.topic, research_output.model_dump_json())

        sections: list[ReportSection] = []
        all_blockers: list[str] = []
        verifier_outputs: list[VerifierOutput] = []
        writer = ReportWriterAgent(router)
        verifier = VerifierAgent(router, use_llm=False)

        for order, section_title in enumerate(planner_output.outline):
            section_id = f"{job.id}-section-{order + 1}"
            section_count = len(planner_output.outline)
            writer_context = self._writer_context(planner, section_title, sections)
            evidence = self._writer_evidence(
                section_title=section_title,
                writer_context=writer_context,
                sources=sources,
                retriever=research_agent.last_retriever,
            )
            set_progress(
                ReportStatus.RUNNING,
                "ReportWriterAgent",
                f"drafting section {order + 1}/{section_count}",
                40.0 + (order / max(section_count, 1)) * 35.0,
            )
            writer_output = writer.write(
                WriterInput(
                    job_id=job.id,
                    section_title=section_title,
                    evidence=evidence,
                    rolling_summary=writer_context,
                )
            )
            claims = [
                claim.model_copy(
                    update={
                        "section_id": section_id,
                        "source_ids": self._source_ids_for_claim(claim, sources),
                    }
                )
                for claim in writer_output.claims
            ]
            append_trace("ReportWriterAgent", section_title, writer_output.model_dump_json())

            set_progress(
                ReportStatus.RUNNING,
                "VerifierAgent",
                f"checking section {order + 1}/{section_count}",
                75.0 + (order / max(section_count, 1)) * 15.0,
            )
            draft_section = ReportSection(
                id=section_id,
                job_id=job.id,
                title=writer_output.section_title,
                content=writer_output.content,
                order=order,
                status="drafted",
                sources=[source.id for source in sources],
                claims=claims,
            )
            verifier_output = verifier.run(draft_section, sources)
            append_trace(
                "VerifierAgent",
                f"{len(claims)} claims in {section_title}",
                verifier_output.model_dump_json(),
            )

            verifier_outputs.append(verifier_output)
            all_blockers.extend(verifier_output.blockers)
            section_status = "blocked" if verifier_output.blockers else "drafted"
            sections.append(
                draft_section.model_copy(
                    update={"status": section_status, "claims": verifier_output.claims}
                )
            )

        set_progress(ReportStatus.RUNNING, "CriticAgent", "reviewing report quality", 95.0)
        critic_output = CriticAgent(router, use_llm=False).run(
            CriticInput(
                report_markdown=self._report_markdown(sections),
                sources=sources,
                verifier_results=verifier_outputs,
                report_plan=getattr(planner, "last_manifest", None) or planner_output,
                section_outputs=sections,
            )
        )
        append_trace("CriticAgent", job.topic, critic_output.model_dump_json())

        return JobRunResult(
            status=self._final_status(job, has_blockers=bool(all_blockers)),
            sections=sections,
            sources=sources,
        )

    @classmethod
    def _writer_evidence(
        cls,
        *,
        section_title: str,
        writer_context: str,
        sources: list[Source],
        retriever,
    ) -> list[str]:
        """Return cited evidence for a section, using RAG hits when available."""
        if retriever is None:
            return cls._source_evidence(sources)

        query = f"{section_title}\n{writer_context}".strip()
        hits = retriever.retrieve(query, limit=max(6, len(sources)))
        source_by_id = {source.id: source for source in sources}
        evidence: list[str] = []
        seen: set[tuple[str, str]] = set()

        for hit in hits:
            source = source_by_id.get(getattr(hit, "source_id", ""))
            text = str(getattr(hit, "text", "")).strip()
            if source is None or not text:
                continue
            key = (source.id, text)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(cls._source_evidence_text(source, text))

        return evidence or cls._source_evidence(sources)

    @classmethod
    def _source_evidence(cls, sources: list[Source]) -> list[str]:
        """Return flat cited source text for writer compatibility."""
        return [cls._source_evidence_text(source, source.raw_text) for source in sources]

    @staticmethod
    def _source_evidence_text(source: Source, text: str) -> str:
        """Format one source as cited evidence for the writer."""
        return f"Citation: {source.citation_key}\nTitle: {source.title}\nURL: {source.url or ''}\n\n{text}"

    @staticmethod
    def _report_markdown(sections: list[ReportSection]) -> str:
        """Return a compact final report draft for advisory quality review."""
        return "\n\n".join(section.content for section in sections if section.content).strip()

    @staticmethod
    def _rolling_summary(sections: list[ReportSection]) -> str:
        """Return a compact summary of previously drafted sections."""
        if not sections:
            return ""
        snippets = [f"{section.title}: {section.content[:240]}" for section in sections[-3:]]
        return "\n".join(snippets)

    @staticmethod
    def _writer_context(
        planner: PlannerAgent, section_title: str, sections: list[ReportSection]
    ) -> str:
        """Return section plan JSON plus recent section summary for writer compatibility."""
        section_plan = planner.section_plan_for_writer(section_title)
        rolling_summary = ReportPipeline._rolling_summary(sections)
        if section_plan and rolling_summary:
            return f"{section_plan}\n\nRolling summary:\n{rolling_summary}"
        return section_plan or rolling_summary

    @staticmethod
    def _source_ids_for_claim(claim, sources: list[Source]) -> list[str]:
        """Map citation-key claim references to stored Source ids."""
        by_key = {source.citation_key.strip("[]"): source.id for source in sources}
        valid_ids = {source.id for source in sources}
        mapped = [by_key[source_id] for source_id in claim.source_ids if source_id in by_key]
        direct = [source_id for source_id in claim.source_ids if source_id in valid_ids]
        return mapped or direct or [source.id for source in sources]

    @staticmethod
    def _final_status(job: ReportJob, *, has_blockers: bool) -> ReportStatus:
        """Resolve final job status from verification and HITL rules."""
        if has_blockers:
            return ReportStatus.FAILED
        if requires_approval(job.type, job.depth):
            return ReportStatus.AWAITING_APPROVAL
        return ReportStatus.COMPLETED


class JobManager:
    """In-memory MVP job manager with SQLite trace/job persistence."""

    def __init__(
        self, store: ReportStore | None = None, pipeline: ReportPipeline | None = None
    ) -> None:
        """Initialize empty job manager."""
        self.store = store or ReportStore()
        self.pipeline = pipeline or ReportPipeline()
        self.jobs: dict[str, ReportJob] = {}
        self.sources_by_job: dict[str, list[Source]] = {}
        self.traces_by_job: dict[str, list[AgentTrace]] = {}
        self.progress_by_job: dict[str, JobProgress] = {}
        self.urls_by_job: dict[str, list[str]] = {}
        self.providers_by_job: dict[str, str] = {}

    def create_job(
        self, request: CreateJobRequest, *, session_id: str = "anonymous"
    ) -> CreateJobResponse:
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
        self.providers_by_job[job_id] = request.provider
        self.progress_by_job[job_id] = JobProgress(
            job_id=job_id, status=job.status, current_step="queued"
        )
        self.store.save_job_inputs(job_id, urls=request.urls, provider=request.provider)
        self.store.save_job(job)
        logger.info(
            "job_created", job_id=job_id, topic=request.topic, report_type=request.type.value
        )
        return CreateJobResponse(job_id=job_id, status=job.status)

    def progress(self, job_id: str) -> JobProgress:
        """Return progress for a job."""
        self._ensure_loaded(job_id)
        return self.progress_by_job[job_id]

    def get_job(self, job_id: str) -> ReportJob:
        """Return a full job snapshot."""
        self._ensure_loaded(job_id)
        return self.jobs[job_id]

    def list_sources(self, job_id: str) -> list[Source]:
        """Return all sources for a job."""
        self._ensure_loaded(job_id)
        return self.sources_by_job[job_id]

    def list_sections(self, job_id: str) -> list[ReportSection]:
        """Return all report sections for a job."""
        self._ensure_loaded(job_id)
        return self.jobs[job_id].sections

    def list_traces(self, job_id: str) -> list[AgentTrace]:
        """Return all execution traces for a job."""
        self._ensure_loaded(job_id)
        return self.traces_by_job[job_id]

    def run_job(self, job_id: str) -> None:
        """Run the zero-cost MVP report workflow for an accepted job."""
        self._ensure_loaded(job_id)
        job = self.jobs[job_id]
        provider = self.providers_by_job.get(job_id, "gemini")
        try:
            result = self.pipeline.run(
                job=job,
                urls=self.urls_by_job.get(job_id, []),
                provider=provider,
                set_progress=lambda status, active_agent, step, percent: self._set_progress(
                    job_id,
                    status,
                    active_agent,
                    step,
                    percent,
                ),
                append_trace=lambda agent_name, input_text, output_text: self._append_trace(
                    job_id,
                    agent_name,
                    input_text,
                    output_text,
                ),
            )
            self.sources_by_job[job_id] = result.sources
            self.store.save_sources(job_id, result.sources)
            job.sections = result.sections
            job.status = result.status
            job.completed_at = self._completed_at(result.status)
            self._set_progress(
                job_id, result.status, None, result.status.value, 100.0, cost=job.cost
            )
            self._persist_job(job)
            logger.info("job_completed", job_id=job_id, status=job.status.value, provider=provider)
        except Exception as exc:
            self._mark_failed(job_id, exc)

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
                self._append_trace(
                    job_id, "SectionRegenerator", feedback, updated.model_dump_json()
                )
                self._persist_job(self.jobs[job_id])
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
        """Retry a job by clearing generated output and running the pipeline again."""
        self._reset_for_retry(job_id)
        self.run_job(job_id)

    def cost_summary(self) -> dict[str, float | int]:
        """Return aggregate zero-cost testing metrics."""
        total_tokens = sum(
            trace.tokens for traces in self.traces_by_job.values() for trace in traces
        )
        estimated_kimi = sum(
            float(trace.estimated_kimi_cost_usd)
            for traces in self.traces_by_job.values()
            for trace in traces
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

    def _append_trace(
        self, job_id: str, agent_name: str, input_text: str, output_text: str
    ) -> None:
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
        self.store.add_trace(trace)

    def _rollup_cost(self, job_id: str) -> CostMetrics:
        """Aggregate per-trace token and estimated cost metrics for a job."""
        traces = self.traces_by_job[job_id]
        total_tokens = sum(trace.tokens for trace in traces)
        estimated_kimi = sum((trace.estimated_kimi_cost_usd for trace in traces), Decimal("0.00"))
        settings = get_settings()
        provider = self.providers_by_job.get(job_id, settings.active_llm_provider)
        model_names = {
            "gemini": settings.gemini_model_name,
            "groq": settings.groq_model_name,
            "ollama": settings.ollama_model_name,
            "kimi": settings.kimi_model_name,
        }
        return CostMetrics(
            prompt_tokens=total_tokens,
            completion_tokens=0,
            estimated_cost_usd=Decimal("0.00"),
            estimated_kimi_cost_usd=estimated_kimi,
            model_name=model_names.get(provider, "unknown"),
        )

    def _persist_job(self, job: ReportJob) -> None:
        """Persist the current job lifecycle state to SQLite."""
        self.store.save_job(job)

    def _mark_failed(self, job_id: str, exc: Exception) -> None:
        """Mark a job failed after pipeline execution raises."""
        logger.exception("job_failed", job_id=job_id, error=str(exc))
        job = self.jobs[job_id]
        job.status = ReportStatus.FAILED
        job.completed_at = None
        self._set_progress(job_id, ReportStatus.FAILED, None, str(exc), 100.0)
        self._persist_job(job)

    def _reset_for_retry(self, job_id: str) -> None:
        """Clear generated output before a full retry run."""
        self._ensure_loaded(job_id)
        job = self.jobs[job_id]
        job.status = ReportStatus.PENDING
        job.completed_at = None
        job.sections = []
        self.sources_by_job[job_id] = []
        self.store.save_sources(job_id, [])
        self._set_progress(job_id, ReportStatus.PENDING, None, "retrying", 0.0)
        self._persist_job(job)

    def _ensure_loaded(self, job_id: str) -> None:
        """Load a persisted job snapshot into memory when needed."""
        if job_id in self.jobs:
            return
        stored = self.store.load_report(job_id)
        if stored is None:
            raise KeyError(job_id)
        self.jobs[job_id] = stored.job
        self.sources_by_job[job_id] = stored.sources
        self.traces_by_job[job_id] = stored.traces
        self.urls_by_job[job_id] = stored.urls
        self.providers_by_job[job_id] = stored.provider
        self.progress_by_job[job_id] = self._progress_from_job(stored.job)

    @staticmethod
    def _progress_from_job(job: ReportJob) -> JobProgress:
        """Build fallback progress for a rehydrated job."""
        terminal_statuses = {
            ReportStatus.AWAITING_APPROVAL,
            ReportStatus.COMPLETED,
            ReportStatus.FAILED,
        }
        return JobProgress(
            job_id=job.id,
            status=job.status,
            current_step=job.status.value,
            percent_complete=100.0 if job.status in terminal_statuses else 0.0,
            cost=job.cost,
        )

    @staticmethod
    def _completed_at(status: ReportStatus) -> str | None:
        """Return completion timestamp only for non-approval terminal success."""
        if status == ReportStatus.AWAITING_APPROVAL:
            return None
        return datetime.now(timezone.utc).isoformat()
