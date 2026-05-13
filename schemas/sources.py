"""Source, evidence, and claim schemas."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationStatus(StrEnum):
    """Verifier outcomes for generated claims."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"


class Source(BaseModel):
    """Research or uploaded evidence source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    title: str
    url: str | None = None
    date: str | None = None
    summary: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_text: str = ""
    citation_key: str

    @field_validator("citation_key")
    @classmethod
    def citation_key_must_be_bracketed(cls, value: str) -> str:
        """Require bracket-key citations such as [AuthorYear] or [SourceID]."""
        if not (value.startswith("[") and value.endswith("]")):
            raise ValueError("citation_key must use bracket format")
        return value


class EvidenceChunk(BaseModel):
    """Retrievable chunk of source text."""

    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    source_id: str
    text: str
    chunk_index: int = Field(ge=0)
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)


class Claim(BaseModel):
    """A generated report claim linked to source evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str
    section_id: str
    text: str
    source_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def blocks_export(self) -> bool:
        """Return whether this claim blocks export."""
        return self.verification_status in {
            VerificationStatus.UNSUPPORTED,
            VerificationStatus.CONTRADICTED,
        }
