"""Pure pricing logic for free-tier model calls."""

from decimal import Decimal

from schemas.costs import CostMetrics


class CostEstimator:
    """Compute actual model costs for configured free-tier providers."""

    def estimate(
        self,
        *,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int = 0,
    ) -> CostMetrics:
        """Return cost metrics for a model call."""
        return CostMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=Decimal("0.00"),
            latency_ms=latency_ms,
            model_name=model_name,
        )
