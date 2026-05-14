"""Provider-neutral model routing for agents."""

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
        """Call the routed provider or return deterministic text when unconfigured."""
        if self.provider == "groq" and self.api_key:
            return self._call_groq(prompt)
        if self.provider == "ollama":
            return self._call_ollama(prompt)
        return f"[{self.provider}:{self.model_name}] {prompt}"

    def _call_groq(self, prompt: str) -> str:
        """Call Groq's OpenAI-compatible chat completions API."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Groq API call failed: {exc}") from exc
        return str(data["choices"][0]["message"]["content"])

    def _call_ollama(self, prompt: str) -> str:
        """Call a local Ollama generate endpoint."""
        payload = {"model": self.model_name, "prompt": prompt, "stream": False}
        request = Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Ollama API call failed at {self.base_url}: {exc}") from exc
        return str(data.get("response", ""))


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
            "ollama": (self.settings.ollama_model_name, "", self.settings.ollama_base_url),
            "kimi": (self.settings.kimi_model_name, self.settings.kimi_api_key, ""),
        }
        if active not in configs:
            raise ValueError(f"Unsupported provider: {active}")
        model_name, api_key, base_url = configs[active]
        return RoutedModel(provider=active, model_name=model_name, api_key=api_key, base_url=base_url)
