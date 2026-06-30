"""FastAPI request and response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.costs import CostMetrics
from schemas.reports import ReportDepth, ReportStatus, ReportType

LLMProvider = Literal["nvidia", "groq", "ollama"]


class CreateJobRequest(BaseModel):
    """Request body for creating a report job."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=3)
    type: ReportType
    depth: ReportDepth
    urls: list[str] = Field(default_factory=list)
    provider: LLMProvider = "nvidia"


class CreateJobResponse(BaseModel):
    """Response returned when a report job is accepted."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: ReportStatus
    estimated_cost_usd: float = 0.0


class JobProgress(BaseModel):
    """Lightweight job progress response."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: ReportStatus
    active_agent: str | None = None
    current_step: str = "queued"
    percent_complete: float = Field(default=0.0, ge=0.0, le=100.0)
    cost: CostMetrics = Field(default_factory=CostMetrics)
