from decimal import Decimal

import pytest

from app.config import Settings
from tools.llm.cost_estimator import CostEstimator
from tools.llm.model_router import ModelRouter, ProviderBlockedError


def test_cost_estimator_records_zero_actual_and_kimi_estimate():
    metrics = CostEstimator().estimate(
        model_name="gemini-1.5-flash",
        prompt_tokens=1000,
        completion_tokens=500,
    )

    assert metrics.estimated_cost_usd == Decimal("0.00")
    assert metrics.estimated_kimi_cost_usd > Decimal("0.00")


def test_model_router_blocks_kimi_when_cost_guard_is_zero():
    settings = Settings(ACTIVE_LLM_PROVIDER="kimi", MAX_COST_USD_PER_JOB=0.0)
    router = ModelRouter(settings)

    with pytest.raises(ProviderBlockedError):
        router.get_model()
