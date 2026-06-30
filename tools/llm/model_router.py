"""Provider-neutral model routing for agents."""

import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.config import Settings, get_settings


@dataclass
class RoutedModel:
    """Small AgentScope-compatible model wrapper used by MVP agents."""

    provider: str
    model_name: str
    api_key: str = ""
    base_url: str = ""
    timeout_seconds: int = 600
    num_ctx: int = 16384
    num_predict: int = 2048
    fallback_provider: str | None = None
    fallback_model_name: str = ""
    fallback_api_key: str = ""
    fallback_base_url: str = ""

    def __call__(self, prompt: str) -> str:
        """Call the routed provider or return deterministic text when unconfigured."""
        if self.provider == "nvidia" and self._has_real_api_key():
            try:
                return self._call_openai_compatible_chat(prompt, "NVIDIA NIM")
            except Exception as nvidia_exc:
                if self.fallback_provider == "groq" and self._has_real_api_key(self.fallback_api_key):
                    try:
                        return self._call_openai_compatible_chat(
                            prompt,
                            "Groq",
                            model_name=self.fallback_model_name,
                            api_key=self.fallback_api_key,
                            base_url=self.fallback_base_url,
                        )
                    except Exception as groq_exc:
                        raise RuntimeError(
                            "NVIDIA NIM API call failed first; Groq fallback failed: "
                            f"{groq_exc}. Original NVIDIA error: {nvidia_exc}"
                        ) from groq_exc
                raise
        if self.provider == "groq" and self._has_real_api_key():
            return self._call_openai_compatible_chat(prompt, "Groq")
        if self.provider == "ollama":
            return self._call_ollama(prompt)
        return f"[{self.provider}:{self.model_name}] {prompt}"

    def _has_real_api_key(self, api_key: str | None = None) -> bool:
        """Return whether a provider key looks configured."""
        key = self.api_key if api_key is None else api_key
        return bool(key and not key.startswith("your-"))

    def _call_openai_compatible_chat(
        self,
        prompt: str,
        provider_label: str,
        *,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> str:
        """Call an OpenAI-compatible chat completions endpoint."""
        active_model = model_name or self.model_name
        payload = {
            "model": active_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": self.num_predict,
        }
        if provider_label == "Groq" and active_model == "qwen/qwen3-32b":
            payload["reasoning_effort"] = "none"
        request = Request(
            f"{(base_url or self.base_url).rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key or self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "reportforge-local/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds, context=_ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"{provider_label} API call failed: {exc}") from exc
        content = data["choices"][0]["message"].get("content", "")
        if isinstance(content, list):
            return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content)

    def _call_ollama(self, prompt: str) -> str:
        """Call a local Ollama generate endpoint."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        request = Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Ollama API call failed at {self.base_url}: {exc}") from exc
        return str(data.get("response", ""))


def _ssl_context() -> ssl.SSLContext:
    """Return a certificate bundle that works on local macOS Python installs."""
    return ssl.create_default_context(cafile=certifi.where())


class ModelRouter:
    """Resolve the active model provider without leaking clients into agents."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize router with runtime settings."""
        self.settings = settings or get_settings()

    def get_model(self, provider: str | None = None) -> RoutedModel:
        """Return a routed model wrapper for the active or requested provider."""
        active = (provider or self.settings.active_llm_provider).lower()
        configs = {
            "nvidia": (
                self.settings.nvidia_model_name,
                self.settings.nvidia_api_key,
                self.settings.nvidia_base_url,
            ),
            "groq": (self.settings.groq_model_name, self.settings.groq_api_key, "https://api.groq.com/openai/v1"),
            "ollama": (self.settings.ollama_model_name, "", self.settings.ollama_base_url),
        }
        if active not in configs:
            raise ValueError(f"Unsupported provider: {active}")
        model_name, api_key, base_url = configs[active]
        return RoutedModel(
            provider=active,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=self.settings.ollama_timeout_seconds if active == "ollama" else 600,
            num_ctx=self.settings.ollama_num_ctx if active == "ollama" else 16384,
            num_predict=self.settings.ollama_num_predict if active == "ollama" else 2048,
            fallback_provider="groq" if active == "nvidia" else None,
            fallback_model_name=self.settings.groq_model_name if active == "nvidia" else "",
            fallback_api_key=self.settings.groq_api_key if active == "nvidia" else "",
            fallback_base_url="https://api.groq.com/openai/v1" if active == "nvidia" else "",
        )
