from pathlib import Path

import pytest

from incident_agent import config
from incident_agent.config import Settings


def test_defaults_without_env_file() -> None:
    s = Settings(_env_file=None)
    assert s.gemini_api_key is None
    assert s.groq_api_key is None
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.database_url == "postgresql+psycopg://incident:incident@localhost:5433/incident_agent"
    assert s.agent_model == "gemini:gemini-flash-latest"
    assert s.fallback_models == ["groq:openai/gpt-oss-120b", "ollama:qwen3:4b"]
    assert s.grader_model == "groq:qwen/qwen3.8-27b"


def test_plain_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-secret")
    monkeypatch.setenv("AGENT_MODEL", "groq:llama")
    monkeypatch.setenv("FALLBACK_MODELS", '["ollama:qwen3:4b"]')
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:1/d")
    s = Settings(_env_file=None)
    assert s.gemini_api_key is not None
    assert s.gemini_api_key.get_secret_value() == "g-secret"
    assert s.agent_model == "groq:llama"
    assert s.fallback_models == ["ollama:qwen3:4b"]
    assert s.database_url == "postgresql+psycopg://u:p@h:1/d"


def test_secrets_are_masked() -> None:
    s = Settings(_env_file=None, groq_api_key="very-secret")  # type: ignore[arg-type]
    assert "very-secret" not in repr(s)
    assert "very-secret" not in str(s)


def test_loads_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=from-file\nUNRELATED=1\n", encoding="utf-8")
    s = Settings(_env_file=env_file)
    assert s.groq_api_key is not None
    assert s.groq_api_key.get_secret_value() == "from-file"


def test_env_file_is_resolved_from_repo_root() -> None:
    assert Path(str(Settings.model_config["env_file"])) == config.REPO_ROOT / ".env"
    assert (config.REPO_ROOT / "docs" / "PLAN.md").exists()


def test_get_settings_is_cached() -> None:
    config.get_settings.cache_clear()
    assert config.get_settings() is config.get_settings()
    config.get_settings.cache_clear()
