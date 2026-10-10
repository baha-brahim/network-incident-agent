"""Application settings. Loads `.env` from the repo root; plain env vars also work."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/incident_agent/config.py -> repo root is three levels above the package directory.
REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATABASE_URL = "postgresql+psycopg://incident:incident@localhost:5433/incident_agent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"
    database_url: str = DEFAULT_DATABASE_URL

    # Model roles, as "provider:model" strings.
    agent_model: str = "gemini:gemini-flash-latest"
    # As an env var, give a JSON list: FALLBACK_MODELS='["groq:openai/gpt-oss-120b"]'
    fallback_models: list[str] = ["groq:openai/gpt-oss-120b", "ollama:qwen3:4b"]
    grader_model: str = "groq:qwen/qwen3.8-27b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
