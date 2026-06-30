import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def offline_provider_env(monkeypatch):
    """Keep tests offline even when the developer .env has real provider keys."""
    monkeypatch.setenv("ACTIVE_LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("NVIDIA_MODEL_NAME", "deepseek-ai/deepseek-v4-flash")
    monkeypatch.setenv("GROQ_MODEL_NAME", "qwen/qwen3-32b")
    monkeypatch.setenv("NVIDIA_REQUESTS_PER_MINUTE_LIMIT", "0")
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE_LIMIT", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
