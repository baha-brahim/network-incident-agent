"""Application settings. Loads `.env` from the repo root; plain env vars also work."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

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
    # Read-only connection used by every agent tool. Defaults to database_url with the
    # agent_ro role; set it explicitly where the credentials differ (e.g. Neon).
    agent_database_url: str | None = None
    # Where fastembed stores the downloaded embedding model.
    embedding_cache_dir: Path = REPO_ROOT / ".cache" / "fastembed"

    # Model roles, as "provider:model" strings.
    agent_model: str = "gemini:gemini-3.5-flash-lite"
    # As an env var, give a JSON list: FALLBACK_MODELS='["groq:openai/gpt-oss-120b"]'
    fallback_models: list[str] = [
        "gemini:gemini-3.1-flash-lite",
        "groq:openai/gpt-oss-120b",
        "ollama:qwen3:4b",
    ]
    grader_model: str = "groq:qwen/qwen3.8-27b"

    # LLM response cache. off = always call; readwrite = reuse and record; replay = never
    # call a provider and fail on a miss (used by CI).
    llm_cache_mode: Literal["off", "readwrite", "replay"] = "off"
    llm_cache_dir: Path = REPO_ROOT / ".llm_cache"
    # Minimum seconds between two calls to the same model (free tiers are rate-limited).
    llm_min_interval_seconds: float = 4.5

    # HTTP API. Live investigations call the model, so they are switchable and limited per day.
    live_enabled: bool = True
    live_daily_limit: int = Field(default=20, ge=0)
    # As an env var, give a JSON list: CORS_ORIGINS='["https://demo.example.org"]'
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def agent_db_url(self) -> str:
        if self.agent_database_url:
            return self.agent_database_url
        url = make_url(self.database_url).set(username="agent_ro", password="agent_ro")
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
