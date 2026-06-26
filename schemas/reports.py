"""Report job and section schemas."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.costs import CostMetrics
from schemas.sources import Claim

SectionStatus = Literal["pending", "drafted", "blocked", "regenerated"]


class ReportType(StrEnum):
    """Supported report types."""

    MARKET_RESEARCH = "market_research"
    COMPANY_PROFILE = "company_profile"
    TECHNICAL_REPORT = "technical_report"
    INVESTMENT_MEMO = "investment_memo"
    COMPETITIVE_ANALYSIS = "competitive_analysis"
    POLICY_BRIEF = "policy_brief"
    LITERATURE_REVIEW = "literature_review"


class ReportDepth(StrEnum):
    """Supported report depth choices."""

    BRIEF = "brief"
    STANDARD = "standard"
    DEEP = "deep"


class ReportStatus(StrEnum):
    """Report job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportSection(BaseModel):
    """A section of a generated report."""

    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    title: str
    content: str = ""
    order: int = Field(ge=0)
    status: SectionStatus = "pending"
    sources: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)


class ReportJob(BaseModel):
    """A report generation job owned by an anonymous session."""

    model_config = ConfigDict(extra="forbid")

    id: str
    topic: str
    type: ReportType
    depth: ReportDepth
    status: ReportStatus = ReportStatus.PENDING
    cost: CostMetrics = Field(default_factory=CostMetrics)
    created_at: str
    completed_at: str | None = None
    session_id: str = "anonymous"
    sections: list[ReportSection] = Field(default_factory=list)
