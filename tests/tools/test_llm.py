from decimal import Decimal

import pytest

from app.config import Settings
from app.database import QuotaCounterRecord, SessionLocal, init_db
from tools.llm.cost_estimator import CostEstimator
from tools.llm.model_router import ModelRouter, ProviderBlockedError
from tools.llm.quota_manager import QuotaExceededError, QuotaLimits, QuotaManager


@pytest.fixture(autouse=True)
def clear_quota_counters():
    init_db()
    with SessionLocal() as session:
        session.query(QuotaCounterRecord).delete()
        session.commit()


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


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("gemini", "gemini-1.5-flash"),
        ("groq", "llama-3.1-70b-versatile"),
        ("ollama", "llama3.1:8b"),
        ("kimi", "kimi-k2.6"),
    ],
)
def test_model_router_supports_all_providers(provider, expected_model):
    settings = Settings(ACTIVE_LLM_PROVIDER=provider, MAX_COST_USD_PER_JOB=1.0)

    model = ModelRouter(settings).get_model()

    assert model.provider == provider
    assert model.model_name == expected_model


def test_model_router_reads_provider_api_key_and_ollama_base_url():
    settings = Settings(
        ACTIVE_LLM_PROVIDER="gemini",
        GEMINI_API_KEY="gemini-key",
        MAX_COST_USD_PER_JOB=1.0,
    )

    gemini = ModelRouter(settings).get_model()
    ollama = ModelRouter(settings).get_model("ollama")

    assert gemini.api_key == "gemini-key"
    assert ollama.base_url == "http://localhost:11434"


def test_quota_manager_enforces_gemini_daily_request_limit():
    manager = QuotaManager(QuotaLimits(gemini_requests_per_day=1, groq_tokens_per_day=1_000_000))

    manager.check_and_increment("gemini")

    with pytest.raises(QuotaExceededError):
        manager.check_and_increment("gemini")


def test_quota_manager_enforces_groq_daily_token_limit():
    manager = QuotaManager(QuotaLimits(gemini_requests_per_day=1500, groq_tokens_per_day=10))

    manager.check_and_increment("groq", tokens=8)

    with pytest.raises(QuotaExceededError):
        manager.check_and_increment("groq", tokens=3)
