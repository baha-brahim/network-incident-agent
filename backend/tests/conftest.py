import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from incident_agent.config import DEFAULT_DATABASE_URL, Settings, get_settings
from incident_agent.db.session import get_agent_engine, get_engine, get_session_factory

SETTINGS_ENV_VARS = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OLLAMA_BASE_URL",
    "DATABASE_URL",
    "AGENT_MODEL",
    "FALLBACK_MODELS",
    "GRADER_MODEL",
    "EMBEDDING_CACHE_DIR",
    "AGENT_DATABASE_URL",
    "LLM_CACHE_MODE",
    "LLM_CACHE_DIR",
    "LLM_MIN_INTERVAL_SECONDS",
    "LIVE_ENABLED",
    "LIVE_DAILY_LIMIT",
    "CORS_ORIGINS",
]

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# Captured at import time, before `clean_env` removes DATABASE_URL. This is the *dev* database;
# db tests only connect to it to create the test database next to it.
DEV_DATABASE_URL = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL

# Arbitrary key so concurrent pytest sessions don't race while setting up the test database.
SETUP_LOCK_KEY = 7_270_001

AGENT_RO_PASSWORD = "agent_ro"  # local dev role, mirrors docker/postgres/init.sql


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


# --- database tests -------------------------------------------------------------------------


def _url_string(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _ensure_test_database(dev_url: URL, test_url: URL) -> None:
    """Create the test database and the read-only role's grants, then migrate it to head."""
    owner = dev_url.username or "incident"
    test_db = test_url.database or ""
    dev = create_engine(dev_url, isolation_level="AUTOCOMMIT")
    test = create_engine(test_url, isolation_level="AUTOCOMMIT")
    quote = dev.dialect.identifier_preparer.quote
    try:
        with dev.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": SETUP_LOCK_KEY})
            try:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_db}
                ).scalar()
                if not exists:
                    conn.execute(text(f"CREATE DATABASE {quote(test_db)}"))
                # Mirrors docker/postgres/init.sql; roles are cluster-wide, grants per database.
                conn.execute(
                    text(
                        "DO $$ BEGIN IF NOT EXISTS "
                        "(SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN "
                        f"CREATE ROLE agent_ro LOGIN PASSWORD '{AGENT_RO_PASSWORD}'; "
                        "END IF; END $$"
                    )
                )
                conn.execute(text("ALTER ROLE agent_ro SET default_transaction_read_only = on"))
                conn.execute(text(f"GRANT CONNECT ON DATABASE {quote(test_db)} TO agent_ro"))
                with test.connect() as tconn:
                    tconn.execute(text("GRANT USAGE ON SCHEMA public TO agent_ro"))
                    tconn.execute(
                        text(
                            f"ALTER DEFAULT PRIVILEGES FOR ROLE {quote(owner)} "
                            "IN SCHEMA public GRANT SELECT ON TABLES TO agent_ro"
                        )
                    )

                # Pass the URL explicitly: migrations/env.py would otherwise read the settings.
                cfg = Config(str(ALEMBIC_INI))
                cfg.set_main_option("sqlalchemy.url", _url_string(test_url).replace("%", "%%"))
                command.upgrade(cfg, "head")

                with test.connect() as tconn:
                    tconn.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_ro"))
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SETUP_LOCK_KEY})
    finally:
        dev.dispose()
        test.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of the `<dev database>_test` database, created and migrated on first use.

    Derived from the dev URL captured at import time; the dev database itself is never modified.
    """
    dev_url = make_url(DEV_DATABASE_URL)
    test_url = dev_url.set(database=f"{dev_url.database}_test")
    _ensure_test_database(dev_url, test_url)
    return _url_string(test_url)


def _reset_app_caches() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    if get_agent_engine.cache_info().currsize:
        get_agent_engine().dispose()
    get_agent_engine.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def db_test_env(
    request: pytest.FixtureRequest, clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """For db-marked tests, point DATABASE_URL (hence settings and `get_engine()`) at the test DB.

    Depends on `clean_env` explicitly so it always runs after DATABASE_URL has been removed.
    Unit tests pass through untouched and never request the database fixtures.
    """
    if request.node.get_closest_marker("db") is None:
        yield
        return
    monkeypatch.setenv("DATABASE_URL", request.getfixturevalue("test_database_url"))
    _reset_app_caches()
    yield
    _reset_app_caches()


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Iterator[Engine]:
    """Owner-role engine on the test database."""
    engine = create_engine(test_database_url)
    with engine.connect() as conn:
        name = conn.execute(text("SELECT current_database()")).scalar_one()
    assert name.endswith("_test"), f"refusing to run db tests against {name!r}"
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def agent_ro_engine(test_database_url: str) -> Iterator[Engine]:
    """Engine as the read-only `agent_ro` role on the test database."""
    url = make_url(test_database_url).set(username="agent_ro", password=AGENT_RO_PASSWORD)
    engine = create_engine(url)
    yield engine
    engine.dispose()
