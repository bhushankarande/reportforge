"""Pure pricing logic for free-tier and Kimi-equivalent estimates."""

from dataclasses import dataclass
from decimal import Decimal

from schemas.costs import CostMetrics


@dataclass(frozen=True)
class Pricing:
    """Per-million-token pricing table entry."""

    input_per_million: Decimal
    output_per_million: Decimal


class CostEstimator:
    """Compute actual and migration-planning model costs."""

    kimi_pricing = Pricing(Decimal("0.15"), Decimal("2.50"))

    def estimate(
        self,
        *,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int = 0,
        actual_free_tier: bool = True,
    ) -> CostMetrics:
        """Return cost metrics for a model call."""
        actual = Decimal("0.00") if actual_free_tier else self._cost(prompt_tokens, completion_tokens)
        kimi = self._cost(prompt_tokens, completion_tokens)
        return CostMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=actual,
            latency_ms=latency_ms,
            model_name=model_name,
            estimated_kimi_cost_usd=kimi,
        )

    def _cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Compute Kimi-equivalent cost from token counts."""
        input_cost = Decimal(prompt_tokens) / Decimal(1_000_000) * self.kimi_pricing.input_per_million
        output_cost = (
            Decimal(completion_tokens) / Decimal(1_000_000) * self.kimi_pricing.output_per_million
        )
        return (input_cost + output_cost).quantize(Decimal("0.000001"))
