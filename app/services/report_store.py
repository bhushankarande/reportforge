"""Persistence module for report jobs, sections, sources, and traces."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import (
    AgentTraceRecord,
    Base,
    JobInputRecord,
    ReportJobRecord,
    ReportSectionRecord,
    SessionLocal,
    SourceRecord,
)
from schemas.costs import AgentTrace, CostMetrics
from schemas.reports import ReportJob, ReportSection
from schemas.sources import Claim, Source


@dataclass(frozen=True)
class StoredReport:
    """A complete persisted report snapshot."""

    job: ReportJob
    sources: list[Source]
    traces: list[AgentTrace]
    urls: list[str]
    provider: str


class ReportStore:
    """SQLite-backed storage for report runtime state."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        """Initialize the store with a SQLAlchemy session factory."""
        self.session_factory = session_factory
        self._ensure_tables()

    def save_job_inputs(self, job_id: str, *, urls: list[str], provider: str) -> None:
        """Persist replayable job inputs."""
        with self.session_factory() as session:
            session.merge(JobInputRecord(job_id=job_id, urls=list(urls), provider=provider))
            session.commit()

    def _ensure_tables(self) -> None:
        """Create missing persistence tables for this store's database bind."""
        with self.session_factory() as session:
            Base.metadata.create_all(bind=session.get_bind())

    def save_job(self, job: ReportJob) -> None:
        """Persist job metadata and generated sections."""
        with self.session_factory() as session:
            session.merge(
                ReportJobRecord(
                    id=job.id,
                    session_id=job.session_id,
                    topic=job.topic,
                    type=job.type.value,
                    depth=job.depth.value,
                    status=job.status.value,
                    cost=float(job.cost.estimated_cost_usd),
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                )
            )
            self._replace_sections(session, job.id, job.sections)
            session.commit()

    def save_sources(self, job_id: str, sources: list[Source]) -> None:
        """Replace stored sources for a job."""
        with self.session_factory() as session:
            session.execute(delete(SourceRecord).where(SourceRecord.job_id == job_id))
            session.add_all(
                SourceRecord(
                    id=source.id,
                    job_id=source.job_id,
                    title=source.title,
                    url=source.url,
                    date=source.date,
                    summary=source.summary,
                    relevance_score=source.relevance_score,
                    raw_text=source.raw_text,
                    citation_key=source.citation_key,
                )
                for source in sources
            )
            session.commit()

    def add_trace(self, trace: AgentTrace) -> None:
        """Persist one execution trace."""
        with self.session_factory() as session:
            session.merge(
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

    def load_report(self, job_id: str) -> StoredReport | None:
        """Load a complete report snapshot by job id."""
        with self.session_factory() as session:
            job_record = session.get(ReportJobRecord, job_id)
            if job_record is None:
                return None
            sections = self._load_sections(session, job_id)
            sources = self._load_sources(session, job_id)
            traces = self._load_traces(session, job_id)
            inputs = session.get(JobInputRecord, job_id)
            job = ReportJob(
                id=job_record.id,
                topic=job_record.topic,
                type=job_record.type,
                depth=job_record.depth,
                status=job_record.status,
                cost=self._cost_from_record(job_record, traces),
                created_at=job_record.created_at,
                completed_at=job_record.completed_at,
                session_id=job_record.session_id,
                sections=sections,
            )
            return StoredReport(
                job=job,
                sources=sources,
                traces=traces,
                urls=list(inputs.urls if inputs is not None else []),
                provider=inputs.provider if inputs is not None else "gemini",
            )

    def _replace_sections(
        self,
        session: Session,
        job_id: str,
        sections: list[ReportSection],
    ) -> None:
        """Replace stored sections for a job within an open transaction."""
        session.execute(delete(ReportSectionRecord).where(ReportSectionRecord.job_id == job_id))
        session.add_all(
            ReportSectionRecord(
                id=section.id,
                job_id=section.job_id,
                title=section.title,
                content=section.content,
                order_index=section.order,
                status=section.status,
                sources=list(section.sources),
                claims=[claim.model_dump(mode="json") for claim in section.claims],
                charts=list(section.charts),
            )
            for section in sections
        )

    def _load_sections(self, session: Session, job_id: str) -> list[ReportSection]:
        """Load report sections in display order."""
        records = session.scalars(
            select(ReportSectionRecord)
            .where(ReportSectionRecord.job_id == job_id)
            .order_by(ReportSectionRecord.order_index)
        ).all()
        return [
            ReportSection(
                id=record.id,
                job_id=record.job_id,
                title=record.title,
                content=record.content,
                order=record.order_index,
                status=record.status,
                sources=list(record.sources or []),
                claims=[Claim.model_validate(claim) for claim in record.claims or []],
                charts=list(record.charts or []),
            )
            for record in records
        ]

    def _load_sources(self, session: Session, job_id: str) -> list[Source]:
        """Load source records for a job."""
        records = session.scalars(select(SourceRecord).where(SourceRecord.job_id == job_id)).all()
        return [
            Source(
                id=record.id,
                job_id=record.job_id,
                title=record.title,
                url=record.url,
                date=record.date,
                summary=record.summary,
                relevance_score=record.relevance_score,
                raw_text=record.raw_text,
                citation_key=record.citation_key,
            )
            for record in records
        ]

    def _load_traces(self, session: Session, job_id: str) -> list[AgentTrace]:
        """Load execution traces for a job."""
        records = session.scalars(
            select(AgentTraceRecord)
            .where(AgentTraceRecord.job_id == job_id)
            .order_by(AgentTraceRecord.created_at)
        ).all()
        return [
            AgentTrace(
                id=record.id,
                job_id=record.job_id,
                agent_name=record.agent_name,
                input=record.input,
                output=record.output,
                tokens=record.tokens,
                cost=Decimal(str(record.cost)),
                estimated_kimi_cost_usd=Decimal(str(record.estimated_kimi_cost_usd)),
                latency_ms=record.latency,
                retry_attempt=record.retry_attempt,
                timestamp=record.created_at,
            )
            for record in records
        ]

    @staticmethod
    def _cost_from_record(job_record: ReportJobRecord, traces: list[AgentTrace]) -> CostMetrics:
        """Rebuild lightweight cost metrics from stored job and trace rows."""
        return CostMetrics(
            prompt_tokens=sum(trace.tokens for trace in traces),
            estimated_cost_usd=Decimal(str(job_record.cost)),
            estimated_kimi_cost_usd=sum(
                (trace.estimated_kimi_cost_usd for trace in traces),
                Decimal("0.00"),
            ),
        )
