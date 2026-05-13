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

    def __call__(self, prompt: str) -> str:
        """Return a deterministic placeholder response for local testing."""
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
        model_names = {
            "gemini": self.settings.gemini_model_name,
            "groq": self.settings.groq_model_name,
            "ollama": self.settings.ollama_model_name,
            "kimi": self.settings.kimi_model_name,
        }
        if active not in model_names:
            raise ValueError(f"Unsupported provider: {active}")
        return RoutedModel(provider=active, model_name=model_names[active])
