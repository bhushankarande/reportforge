"""Provider-neutral model routing for agents."""

from dataclasses import dataclass

from app.config import Settings, get_settings


class ProviderBlockedError(RuntimeError):
    """Raised when a provider is blocked by cost guardrails."""


@dataclass
class RoutedModel:
    """Small AgentScope-compatible model wrapper used by MVP agents."""

    provider: str
    model_name: str
    api_key: str = ""
    base_url: str = ""

    def __call__(self, prompt: str) -> str:
        """Return a deterministic local response for free-tier/offline tests."""
        return f"[{self.provider}:{self.model_name}] {prompt}"


class ModelRouter:
    """Resolve the active model provider without leaking clients into agents."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize router with runtime settings."""
        self.settings = settings or get_settings()

    def get_model(self, provider: str | None = None) -> RoutedModel:
        """Return a routed model wrapper for the active or requested provider."""
        active = (provider or self.settings.active_llm_provider).lower()
        if active == "kimi" and self.settings.max_cost_usd_per_job == 0:
            raise ProviderBlockedError("Kimi is blocked while MAX_COST_USD_PER_JOB=0.00")
        configs = {
            "gemini": (self.settings.gemini_model_name, self.settings.gemini_api_key, ""),
            "groq": (self.settings.groq_model_name, self.settings.groq_api_key, ""),
            "ollama": (self.settings.ollama_model_name, "", "http://localhost:11434"),
            "kimi": (self.settings.kimi_model_name, self.settings.kimi_api_key, ""),
        }
        if active not in configs:
            raise ValueError(f"Unsupported provider: {active}")
        model_name, api_key, base_url = configs[active]
        return RoutedModel(provider=active, model_name=model_name, api_key=api_key, base_url=base_url)
