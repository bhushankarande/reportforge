from decimal import Decimal
from datetime import datetime, timezone
import json
from urllib.error import URLError

import pytest

from app.config import Settings
from app.database import QuotaCounterRecord, SessionLocal, init_db
from tools.llm.cost_estimator import CostEstimator
from tools.llm.model_router import ModelRouter, RoutedModel
from tools.llm.quota_manager import QuotaExceededError, QuotaLimits, QuotaManager


@pytest.fixture(autouse=True)
def clear_quota_counters():
    init_db()
    with SessionLocal() as session:
        session.query(QuotaCounterRecord).delete()
        session.commit()


def test_cost_estimator_records_zero_actual_cost():
    metrics = CostEstimator().estimate(
        model_name="deepseek-ai/deepseek-v4-flash",
        prompt_tokens=1000,
        completion_tokens=500,
    )

    assert metrics.estimated_cost_usd == Decimal("0.00")


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("nvidia", "deepseek-ai/deepseek-v4-flash"),
        ("groq", "qwen/qwen3-32b"),
        ("ollama", "llama3.1:8b"),
    ],
)
def test_model_router_supports_all_providers(provider, expected_model):
    settings = Settings(ACTIVE_LLM_PROVIDER=provider)

    model = ModelRouter(settings).get_model()

    assert model.provider == provider
    assert model.model_name == expected_model


def test_model_router_reads_provider_api_key_and_ollama_base_url():
    settings = Settings(
        ACTIVE_LLM_PROVIDER="nvidia",
        NVIDIA_API_KEY="nvidia-key",
        NVIDIA_BASE_URL="https://nvidia.local/v1",
        OLLAMA_BASE_URL="http://ollama.local:11434",
        OLLAMA_TIMEOUT_SECONDS=900,
        OLLAMA_NUM_CTX=32768,
        OLLAMA_NUM_PREDICT=4096,
    )

    nvidia = ModelRouter(settings).get_model()
    ollama = ModelRouter(settings).get_model("ollama")

    assert nvidia.api_key == "nvidia-key"
    assert nvidia.base_url == "https://nvidia.local/v1"
    assert nvidia.timeout_seconds == 600
    assert ollama.base_url == "http://ollama.local:11434"
    assert ollama.timeout_seconds == 900
    assert ollama.num_ctx == 32768
    assert ollama.num_predict == 4096


def test_nvidia_model_uses_openai_compatible_chat_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"NVIDIA generated report."}}]}'

    def fake_urlopen(request, timeout, **kwargs):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("tools.llm.model_router.urlopen", fake_urlopen)

    output = RoutedModel(
        provider="nvidia",
        model_name="deepseek-ai/deepseek-v4-flash",
        api_key="key",
        base_url="https://integrate.api.nvidia.com/v1",
    )("hello")

    assert output == "NVIDIA generated report."
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer key"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-agent"] == "reportforge-local/0.1"
    assert captured["timeout"] == 600


def test_nvidia_failure_falls_back_to_groq_success(monkeypatch):
    calls = []

    class FakeGroqResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"Groq fallback report."}}]}'

    def fake_urlopen(request, timeout, **kwargs):
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "payload": json.loads(request.data.decode("utf-8")),
            }
        )
        if "integrate.api.nvidia.com" in request.full_url:
            raise URLError("nvidia timeout")
        return FakeGroqResponse()

    monkeypatch.setattr("tools.llm.model_router.urlopen", fake_urlopen)

    output = RoutedModel(
        provider="nvidia",
        model_name="deepseek-ai/deepseek-v4-flash",
        api_key="nvidia-key",
        base_url="https://integrate.api.nvidia.com/v1",
        fallback_provider="groq",
        fallback_model_name="qwen/qwen3-32b",
        fallback_api_key="groq-key",
        fallback_base_url="https://api.groq.com/openai/v1",
    )("hello")

    assert output == "Groq fallback report."
    assert [call["payload"]["model"] for call in calls] == [
        "deepseek-ai/deepseek-v4-flash",
        "qwen/qwen3-32b",
    ]
    assert calls[1]["payload"]["reasoning_effort"] == "none"
    assert calls[1]["headers"]["Authorization"] == "Bearer groq-key"
    assert calls[1]["headers"]["User-agent"] == "reportforge-local/0.1"


def test_nvidia_failure_then_groq_failure_raises_clear_error(monkeypatch):
    def fake_urlopen(request, timeout, **kwargs):
        if "integrate.api.nvidia.com" in request.full_url:
            raise URLError("nvidia timeout")
        raise URLError("groq unavailable")

    monkeypatch.setattr("tools.llm.model_router.urlopen", fake_urlopen)

    model = RoutedModel(
        provider="nvidia",
        model_name="deepseek-ai/deepseek-v4-flash",
        api_key="nvidia-key",
        base_url="https://integrate.api.nvidia.com/v1",
        fallback_provider="groq",
        fallback_model_name="qwen/qwen3-32b",
        fallback_api_key="groq-key",
        fallback_base_url="https://api.groq.com/openai/v1",
    )

    with pytest.raises(RuntimeError, match="NVIDIA NIM API call failed first; Groq fallback failed"):
        model("hello")


def test_active_groq_failure_does_not_fallback(monkeypatch):
    calls = 0

    def fake_urlopen(request, timeout, **kwargs):
        nonlocal calls
        calls += 1
        raise URLError("groq unavailable")

    monkeypatch.setattr("tools.llm.model_router.urlopen", fake_urlopen)

    model = RoutedModel(
        provider="groq",
        model_name="qwen/qwen3-32b",
        api_key="groq-key",
        base_url="https://api.groq.com/openai/v1",
        fallback_provider="nvidia",
        fallback_model_name="deepseek-ai/deepseek-v4-flash",
        fallback_api_key="nvidia-key",
        fallback_base_url="https://integrate.api.nvidia.com/v1",
    )

    with pytest.raises(RuntimeError, match="Groq API call failed"):
        model("hello")

    assert calls == 1


def test_nvidia_missing_key_keeps_deterministic_stub(monkeypatch):
    def fake_urlopen(request, timeout, **kwargs):
        raise AssertionError("Missing NVIDIA key should not call a provider or fallback")

    monkeypatch.setattr("tools.llm.model_router.urlopen", fake_urlopen)

    output = RoutedModel(
        provider="nvidia",
        model_name="deepseek-ai/deepseek-v4-flash",
        fallback_provider="groq",
        fallback_model_name="qwen/qwen3-32b",
        fallback_api_key="groq-key",
        fallback_base_url="https://api.groq.com/openai/v1",
    )("hello")

    assert output == "[nvidia:deepseek-ai/deepseek-v4-flash] hello"


def test_quota_manager_enforces_nvidia_per_minute_request_limit():
    manager = QuotaManager(
        QuotaLimits(
            nvidia_requests_per_minute=1,
            nvidia_requests_per_day=0,
            groq_requests_per_minute=60,
            groq_requests_per_day=1_000,
            groq_tokens_per_day=500_000,
        )
    )

    manager.check_and_increment("nvidia")

    with pytest.raises(QuotaExceededError):
        manager.check_and_increment("nvidia")


def test_quota_manager_enforces_groq_daily_token_limit():
    manager = QuotaManager(
        QuotaLimits(
            nvidia_requests_per_minute=40,
            nvidia_requests_per_day=0,
            groq_requests_per_minute=60,
            groq_requests_per_day=1_000,
            groq_tokens_per_day=10,
        )
    )

    manager.check_and_increment("groq", tokens=8)

    with pytest.raises(QuotaExceededError):
        manager.check_and_increment("groq", tokens=3)


def test_quota_manager_enforces_groq_per_minute_request_limit():
    manager = QuotaManager(
        QuotaLimits(
            nvidia_requests_per_minute=40,
            nvidia_requests_per_day=0,
            groq_requests_per_minute=1,
            groq_requests_per_day=1_000,
            groq_tokens_per_day=500_000,
        )
    )

    manager.check_and_increment("groq")

    with pytest.raises(QuotaExceededError):
        manager.check_and_increment("groq")


@pytest.mark.parametrize(
    ("provider", "remaining_key"),
    [
        ("nvidia", "nvidia_requests_per_minute_remaining"),
        ("groq", "groq_requests_per_minute_remaining"),
    ],
)
def test_quota_manager_uses_rolling_minute_across_clock_minute(provider, remaining_key):
    now = datetime(2026, 1, 1, 12, 0, 59, tzinfo=timezone.utc)

    def clock() -> datetime:
        return now

    manager = QuotaManager(
        QuotaLimits(
            nvidia_requests_per_minute=2,
            nvidia_requests_per_day=0,
            groq_requests_per_minute=2,
            groq_requests_per_day=1_000,
            groq_tokens_per_day=500_000,
        ),
        clock=clock,
    )

    manager.check_and_increment(provider)

    now = datetime(2026, 1, 1, 12, 1, 1, tzinfo=timezone.utc)
    assert manager.status()[remaining_key] == 1

    manager.check_and_increment(provider)
    with pytest.raises(QuotaExceededError):
        manager.check_and_increment(provider)

    now = datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc)
    assert manager.status()[remaining_key] == 1
