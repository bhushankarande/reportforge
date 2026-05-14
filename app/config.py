"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ReportForge runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    active_llm_provider: str = Field(default="gemini", alias="ACTIVE_LLM_PROVIDER")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model_name: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL_NAME")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model_name: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL_NAME")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model_name: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL_NAME")
    kimi_api_key: str = Field(default="", alias="KIMI_API_KEY")
    kimi_model_name: str = Field(default="kimi-k2.6", alias="KIMI_MODEL_NAME")
    max_cost_usd_per_job: float = Field(default=0.0, alias="MAX_COST_USD_PER_JOB")
    enable_cost_preview: bool = Field(default=True, alias="ENABLE_COST_PREVIEW")
    gemini_daily_request_limit: int = Field(default=1500, alias="GEMINI_DAILY_REQUEST_LIMIT")
    groq_daily_token_limit: int = Field(default=1_000_000, alias="GROQ_DAILY_TOKEN_LIMIT")
    storage_dir: str = Field(default="./storage", alias="STORAGE_DIR")
    database_url: str = Field(default="sqlite:///./storage/reportforge.db", alias="DATABASE_URL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached runtime settings."""
    return Settings()
