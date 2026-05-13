"""CostTrackingModel wrapper for routed model calls."""

import time
from dataclasses import dataclass

from app.logging_config import get_logger
from schemas.costs import CostMetrics
from tools.llm.cost_estimator import CostEstimator
from tools.llm.model_router import RoutedModel
from tools.llm.quota_manager import QuotaManager

logger = get_logger(__name__)


@dataclass
class TrackedResponse:
    """A model response plus cost metrics."""

    text: str
    cost: CostMetrics


class CostTrackingModel:
    """Decorate a routed model with cost and latency logging."""

    def __init__(
        self,
        model: RoutedModel,
        estimator: CostEstimator | None = None,
        quota_manager: QuotaManager | None = None,
    ) -> None:
        """Initialize wrapper around a routed model."""
        self.model = model
        self.estimator = estimator or CostEstimator()
        self.quota_manager = quota_manager or QuotaManager()

    def __call__(self, prompt: str) -> TrackedResponse:
        """Invoke the model and return tracked response metadata."""
        started = time.perf_counter()
        prompt_tokens = len(prompt.split())
        self.quota_manager.check_and_increment(self.model.provider, tokens=prompt_tokens)
        response = self.model(prompt)
        latency_ms = int((time.perf_counter() - started) * 1000)
        cost = self.estimator.estimate(
            model_name=self.model.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=len(response.split()),
            latency_ms=latency_ms,
            actual_free_tier=self.model.provider in {"gemini", "groq", "ollama"},
        )
        logger.info(
            "llm_call",
            provider=self.model.provider,
            model=self.model.model_name,
            tokens=cost.total_tokens,
            actual_cost=str(cost.estimated_cost_usd),
            estimated_kimi_cost=str(cost.estimated_kimi_cost_usd),
            latency_ms=latency_ms,
        )
        return TrackedResponse(text=response, cost=cost)
