import pytest
from sqlalchemy import Engine, create_engine, text

from incident_agent.config import get_settings
from incident_agent.db import check_connection, get_engine


@pytest.mark.db
def test_check_connection() -> None:
    check_connection()


@pytest.mark.db
def test_prepare_threshold_none_keeps_statements_unprepared(test_database_url: str) -> None:
    """Behind a transaction pooler a prepared statement may not exist on the next connection."""

    def prepared_after_repeats(**connect_args: object) -> int:
        engine = create_engine(test_database_url, connect_args=connect_args)
        try:
            with engine.connect() as conn:
                for _ in range(10):
                    conn.execute(text("SELECT 1 AS one"))
                return int(
                    conn.execute(text("SELECT count(*) FROM pg_prepared_statements")).scalar_one()
                )
        finally:
            engine.dispose()

    assert prepared_after_repeats() > 0  # psycopg prepares a statement it has run often
    assert prepared_after_repeats(prepare_threshold=None) == 0


@pytest.mark.db
def test_engines_target_the_test_database(
    db_engine: Engine, agent_ro_engine: Engine, test_database_url: str
) -> None:
    """Safety net: nothing under test may be connected to the dev database."""
    assert get_settings().database_url == test_database_url
    for engine in (get_engine(), db_engine, agent_ro_engine):
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one().endswith("_test")
