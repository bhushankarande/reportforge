"""Typed agent input and output contracts."""

from pydantic import BaseModel, ConfigDict, Field

from schemas.sources import Claim, Source


class PlannerOutput(BaseModel):
    """Planner result containing outline and research questions."""

    model_config = ConfigDict(extra="forbid")

    outline: list[str]
    research_questions: list[str]
    target_word_count: int = Field(default=2500, ge=1)


class ResearchOutput(BaseModel):
    """Research agent result with scored sources."""

    model_config = ConfigDict(extra="forbid")

    sources: list[Source]


class DocumentReaderOutput(BaseModel):
    """Document reader result with extracted source ids."""

    model_config = ConfigDict(extra="forbid")

    source_ids: list[str]
    chunks_indexed: int = Field(ge=0)


class WriterInput(BaseModel):
    """Writer input for one report section."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    section_title: str
    evidence: list[str]
    rolling_summary: str = ""


class WriterOutput(BaseModel):
    """Writer output containing section content and claims."""

    model_config = ConfigDict(extra="forbid")

    section_title: str
    content: str
    claims: list[Claim]
    sources_used: list[str] = Field(default_factory=list)


class VerifierOutput(BaseModel):
    """Verifier result with blockers and warnings."""

    model_config = ConfigDict(extra="forbid")

    claims: list[Claim]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CriticOutput(BaseModel):
    """Critic result with quality score and fixes."""

    model_config = ConfigDict(extra="forbid")

    quality_score: float = Field(ge=0.0, le=1.0)
    fixes: list[str] = Field(default_factory=list)


class FormatterOutput(BaseModel):
    """Formatter result with generated artifact paths."""

    model_config = ConfigDict(extra="forbid")

    markdown_path: str | None = None
    pdf_path: str | None = None
    docx_path: str | None = None
