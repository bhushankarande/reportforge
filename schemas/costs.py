"""Cost and token accounting schemas."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class CostMetrics(BaseModel):
    """Token usage and cost estimates for a model call or report job."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal = Field(default=Decimal("0.00"), ge=0)
    latency_ms: int = Field(default=0, ge=0)
    model_name: str = "unknown"
    estimated_kimi_cost_usd: Decimal = Field(default=Decimal("0.00"), ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Return prompt plus completion tokens."""
        return self.prompt_tokens + self.completion_tokens
