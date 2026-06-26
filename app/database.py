"""SQLite database setup and persistence helpers."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import JSON, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base SQLAlchemy model."""


class ReportJobRecord(Base):
    """SQLite record for report job state."""

    __tablename__ = "report_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    topic: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String)
    depth: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class JobInputRecord(Base):
    """SQLite record for replayable job inputs."""

    __tablename__ = "job_inputs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, default="gemini")
    urls: Mapped[list[str]] = mapped_column(JSON, default=list)


class ReportSectionRecord(Base):
    """SQLite record for generated report sections."""

    __tablename__ = "report_sections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="pending")
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    claims: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    charts: Mapped[list[str]] = mapped_column(JSON, default=list)


class SourceRecord(Base):
    """SQLite record for collected source evidence."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    citation_key: Mapped[str] = mapped_column(String)


class AgentTraceRecord(Base):
    """SQLite record for agent execution traces."""

    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    agent_name: Mapped[str] = mapped_column(String)
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_kimi_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency: Mapped[int] = mapped_column(Integer, default=0)
    retry_attempt: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String)


class QuotaCounterRecord(Base):
    """SQLite record for daily quota accounting."""

    __tablename__ = "quota_counters"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


def get_engine():
    """Create the configured SQLAlchemy engine."""
    settings = get_settings()
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url, future=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all SQLite tables."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
