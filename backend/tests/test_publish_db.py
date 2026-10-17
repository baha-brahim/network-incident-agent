"""Publishing the fixture world into a throwaway database on the local server."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from incident_agent.db.publish import PUBLISHED_TABLES, Roles, libpq_url, publish
from tests.test_agent_db import setup_world

pytestmark = pytest.mark.db

THROWAWAY = "incident_agent_test_publish_tmp"
ROLES = Roles("pub_tmp_agent_ro", "agent-pass", "pub_tmp_api_rw", "api-pass")


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


@pytest.fixture(scope="module")
def target_url(test_database_url: str) -> Iterator[str]:
    """An empty database next to the test database; it and the roles it gets are removed after."""
    url = make_url(test_database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    drop_all = [
        f'DROP DATABASE IF EXISTS "{THROWAWAY}" WITH (FORCE)',
        f'DROP ROLE IF EXISTS "{ROLES.agent}"',
        f'DROP ROLE IF EXISTS "{ROLES.api}"',
    ]
    try:
        with admin.connect() as conn:
            for statement in drop_all:
                conn.execute(text(statement))
            conn.execute(text(f'CREATE DATABASE "{THROWAWAY}"'))
        yield url.set(database=THROWAWAY).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            for statement in drop_all:
                conn.execute(text(statement))
        admin.dispose()


def connect(url: str, role: str | None = None, password: str | None = None) -> psycopg.Connection:
    parsed = make_url(url)
    if role is not None:
        parsed = parsed.set(username=role, password=password)
    return psycopg.connect(libpq_url(parsed.render_as_string(hide_password=False)))


def scalar(conn: psycopg.Connection, query: str) -> Any:
    row = conn.execute(query).fetchone()  # type: ignore[call-overload]
    assert row is not None
    return row[0]


@pytest.fixture(scope="module")
def published(world: Engine, target_url: str, test_database_url: str) -> list[str]:
    lines: list[str] = []
    publish(test_database_url, target_url, ROLES, dry_run=False, out=lines.append)
    return lines


def counts(url: str) -> dict[str, int]:
    with connect(url) as conn:
        return {t: scalar(conn, f"SELECT count(*) FROM public.{t}") for t in PUBLISHED_TABLES}


def test_every_public_table_is_published(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
        }
    assert tables - {"alembic_version"} == set(PUBLISHED_TABLES)


def test_row_counts_match_and_no_ground_truth_is_copied(
    published: list[str], target_url: str, test_database_url: str, world: Engine
) -> None:
    source, target = counts(test_database_url), counts(target_url)
    assert target == source
    assert target["nodes"] > 0 and target["cell_kpis"] > 0 and target["runbook_chunks"] > 0
    with connect(target_url) as conn:
        assert scalar(conn, "SELECT count(*) FROM gt.scenarios") == 0
    with world.connect() as sa_conn:
        assert sa_conn.execute(text("SELECT count(*) FROM gt.scenarios")).scalar_one() > 0
    assert published[-1] == "Done."


def test_embeddings_survive_the_copy(published: list[str], target_url: str) -> None:
    with connect(target_url) as conn:
        assert scalar(conn, "SELECT DISTINCT vector_dims(embedding) FROM runbook_chunks") == 384
        assert scalar(conn, "SELECT count(*) FROM runbook_chunks WHERE tsv IS NULL") == 0


def test_the_read_only_role_sees_the_network_and_nothing_else(
    published: list[str], target_url: str
) -> None:
    with connect(target_url, ROLES.agent, ROLES.agent_password) as conn:
        assert scalar(conn, "SELECT count(*) FROM nodes") > 0
        assert scalar(conn, "SELECT count(*) FROM region_kpis_15m") > 0
        assert scalar(conn, "SHOW default_transaction_read_only") == "on"
    for forbidden in ("SELECT * FROM gt.scenarios", "SELECT * FROM app.agent_runs"):
        with (
            connect(target_url, ROLES.agent, ROLES.agent_password) as conn,
            pytest.raises(errors.InsufficientPrivilege),
        ):
            conn.execute(forbidden)  # type: ignore[call-overload]
    with (
        connect(target_url, ROLES.agent, ROLES.agent_password) as conn,
        pytest.raises(errors.Error),
    ):
        conn.execute("INSERT INTO regions VALUES ('X', 'x')")  # type: ignore[call-overload]


def test_the_api_role_writes_the_app_schema_only(published: list[str], target_url: str) -> None:
    with connect(target_url, ROLES.api, ROLES.api_password) as conn:
        assert scalar(conn, "SELECT count(*) FROM nodes") > 0
        conn.execute(  # type: ignore[call-overload]
            "INSERT INTO app.agent_runs (run_id, question, asked_at, trigger, status, started_at) "
            "VALUES ('RUN-PUB', 'q', now(), 'user', 'running', now())"
        )
        conn.execute("UPDATE app.agent_runs SET client_hash = 'abc' WHERE run_id = 'RUN-PUB'")  # type: ignore[call-overload]
        conn.execute("DELETE FROM app.agent_runs WHERE run_id = 'RUN-PUB'")  # type: ignore[call-overload]
    for forbidden in (
        "SELECT * FROM gt.scenarios",
        "INSERT INTO regions VALUES ('X', 'x')",
        "DELETE FROM nodes",
    ):
        with (
            connect(target_url, ROLES.api, ROLES.api_password) as conn,
            pytest.raises(errors.InsufficientPrivilege),
        ):
            conn.execute(forbidden)  # type: ignore[call-overload]


def test_publishing_again_gives_the_same_result(
    published: list[str], target_url: str, test_database_url: str
) -> None:
    publish(test_database_url, target_url, ROLES, dry_run=False, out=lambda _: None)
    assert counts(target_url) == counts(test_database_url)


def test_a_dry_run_lists_the_plan_and_never_connects_to_the_target(
    world: Engine, test_database_url: str
) -> None:
    lines: list[str] = []
    unreachable = "postgresql+psycopg://x:y@127.0.0.1:1/none"
    publish(test_database_url, unreachable, ROLES, dry_run=True, out=lines.append)
    shown = "\n".join(lines)
    assert "nothing is sent" in shown and ROLES.agent in shown
    assert all(table in shown for table in PUBLISHED_TABLES)
