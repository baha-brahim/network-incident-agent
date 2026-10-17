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
    assert s.agent_model == "gemini:gemini-3.5-flash-lite"
    assert s.fallback_models == [
        "gemini:gemini-3.1-flash-lite",
        "groq:openai/gpt-oss-120b",
        "ollama:qwen3:4b",
    ]
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


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+psycopg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/db"
            "?sslmode=require&channel_binding=require",
        ),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_database_urls_use_the_psycopg_driver(
    given: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", given)
    monkeypatch.setenv("AGENT_DATABASE_URL", given)
    s = Settings(_env_file=None)
    assert s.database_url == expected
    assert s.agent_db_url == expected


def test_agent_database_url_is_optional() -> None:
    s = Settings(_env_file=None)
    assert s.agent_database_url is None
    assert s.agent_db_url == "postgresql+psycopg://agent_ro:agent_ro@localhost:5433/incident_agent"


def test_client_limit_settings() -> None:
    s = Settings(_env_file=None)
    assert s.live_per_client_daily_limit == 3 and s.client_hash_salt is None
    with pytest.raises(ValueError):
        Settings(_env_file=None, live_per_client_daily_limit=-1)
    salted = Settings(_env_file=None, client_hash_salt="pepper")  # type: ignore[arg-type]
    assert "pepper" not in repr(salted)


def test_cache_directories_can_be_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CACHE_DIR", "/tmp/llm_cache")
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "/opt/fastembed")
    s = Settings(_env_file=None)
    assert s.llm_cache_dir == Path("/tmp/llm_cache")
    assert s.embedding_cache_dir == Path("/opt/fastembed")
