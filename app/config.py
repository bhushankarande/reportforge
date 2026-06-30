"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ReportForge runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    active_llm_provider: str = Field(default="nvidia", alias="ACTIVE_LLM_PROVIDER")
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_model_name: str = Field(
        default="deepseek-ai/deepseek-v4-flash",
        alias="NVIDIA_MODEL_NAME",
    )
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL",
    )
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model_name: str = Field(default="qwen/qwen3-32b", alias="GROQ_MODEL_NAME")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model_name: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL_NAME")
    ollama_timeout_seconds: int = Field(default=600, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_num_ctx: int = Field(default=16384, alias="OLLAMA_NUM_CTX")
    ollama_num_predict: int = Field(default=3072, alias="OLLAMA_NUM_PREDICT")
    nvidia_requests_per_minute_limit: int = Field(
        default=40,
        alias="NVIDIA_REQUESTS_PER_MINUTE_LIMIT",
    )
    nvidia_daily_request_limit: int = Field(default=0, alias="NVIDIA_DAILY_REQUEST_LIMIT")
    groq_requests_per_minute_limit: int = Field(default=60, alias="GROQ_REQUESTS_PER_MINUTE_LIMIT")
    groq_daily_request_limit: int = Field(default=1_000, alias="GROQ_DAILY_REQUEST_LIMIT")
    groq_daily_token_limit: int = Field(default=500_000, alias="GROQ_DAILY_TOKEN_LIMIT")
    storage_dir: str = Field(default="./storage", alias="STORAGE_DIR")
    database_url: str = Field(default="sqlite:///./storage/reportforge.db", alias="DATABASE_URL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached runtime settings."""
    return Settings()
