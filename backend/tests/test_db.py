import pytest
from sqlalchemy import Engine, text

from incident_agent.config import get_settings
from incident_agent.db import check_connection, get_engine


@pytest.mark.db
def test_check_connection() -> None:
    check_connection()


@pytest.mark.db
def test_engines_target_the_test_database(
    db_engine: Engine, agent_ro_engine: Engine, test_database_url: str
) -> None:
    """Safety net: nothing under test may be connected to the dev database."""
    assert get_settings().database_url == test_database_url
    for engine in (get_engine(), db_engine, agent_ro_engine):
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one().endswith("_test")
