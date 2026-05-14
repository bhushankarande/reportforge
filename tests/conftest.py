import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def offline_provider_env(monkeypatch):
    """Keep tests offline even when the developer .env has real provider keys."""
    monkeypatch.setenv("ACTIVE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
