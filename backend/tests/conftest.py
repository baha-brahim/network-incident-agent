from collections.abc import Callable

import pytest

from incident_agent.config import Settings

SETTINGS_ENV_VARS = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OLLAMA_BASE_URL",
    "DATABASE_URL",
    "AGENT_MODEL",
    "FALLBACK_MODELS",
    "GRADER_MODEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must not depend on the shell environment or a real .env."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def use_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Return a helper that patches the factory's settings with the given values."""

    def _apply(**values: object) -> Settings:
        settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
        monkeypatch.setattr("incident_agent.llm.factory.get_settings", lambda: settings)
        return settings

    return _apply
