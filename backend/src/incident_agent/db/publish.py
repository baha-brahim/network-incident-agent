"""Publish the local dev database to a hosted Postgres (Neon).

uv run python -m incident_agent.db.publish --target-env NEON_DATABASE_URL [--dry-run]

Steps: migrate the target to head, create the two application roles, copy the network data
(`public` tables only: no ground truth, no `app` schema) with COPY, and compare row counts.
The target URL is read from the named environment variable or `.env` and is never printed.
Use the direct connection string of the target, not a pooled one.

Environment: AGENT_RO_PASSWORD and API_RW_PASSWORD, the passwords of the two roles.
"""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from psycopg import IsolationLevel, sql
from sqlalchemy.engine import make_url

from incident_agent.config import REPO_ROOT, get_settings, with_psycopg_driver
from incident_agent.db.session import is_pooled_host

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

# Parents before children (foreign keys). Everything the API and the agent's tools read.
PUBLISHED_TABLES = (
    "regions",
    "nodes",
    "cells",
    "cell_kpis",
    "core_kpis",
    "alarms",
    "changes",
    "maintenance",
    "external_events",
    "dataset_meta",
    "alerts",
    "anomalies",
    "runbook_docs",
    "runbook_chunks",
)
# Emptied on the target so that it never holds the hidden labels (it references `nodes`).
GROUND_TRUTH_TABLE = ("gt", "scenarios")

AGENT_ROLE = "agent_ro"
API_ROLE = "api_rw"
AGENT_PASSWORD_VAR = "AGENT_RO_PASSWORD"
API_PASSWORD_VAR = "API_RW_PASSWORD"

Printer = Callable[[str], None]


class PublishError(Exception):
    pass


@dataclass(frozen=True)
class Roles:
    agent: str
    agent_password: str
    api: str
    api_password: str


def read_setting(name: str) -> str | None:
    """A value from the environment, else from `.env`. Empty counts as unset."""
    value = os.environ.get(name) or dotenv_values(REPO_ROOT / ".env").get(name)
    return value or None


def libpq_url(url: str) -> str:
    """A SQLAlchemy URL as the plain `postgresql://` URL psycopg takes."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def same_database(a: str, b: str) -> bool:
    ua, ub = make_url(a), make_url(b)
    return (ua.host, ua.port or 5432, ua.database) == (ub.host, ub.port or 5432, ub.database)


def secrets_of(*urls: str) -> list[str]:
    """What an error message must not show: the URLs, their passwords and their hosts."""
    found: list[str] = []
    for url in urls:
        parsed = make_url(url)
        found += [
            url,
            with_psycopg_driver(url),
            libpq_url(url),
            parsed.password or "",
            parsed.host or "",
        ]
    return found


def redact(message: str, secrets: list[str]) -> str:
    for secret in sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True):
        message = message.replace(secret, "***")
    return message


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'NEVER' "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def _count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(_ident(table))).fetchone()
    assert row is not None
    return int(row[0])


def _ident(table: str) -> sql.Identifier:
    return sql.Identifier("public", table)


def migrate(target_url: str) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", with_psycopg_driver(target_url).replace("%", "%%"))
    command.upgrade(cfg, "head")


def _run(conn: psycopg.Connection, statement: str, *names: str) -> None:
    """A statement with `{}` placeholders filled by identifiers."""
    conn.execute(sql.SQL(statement).format(*[sql.Identifier(n) for n in names]))


def ensure_role(conn: psycopg.Connection, name: str, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    conn.execute(
        sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(name), sql.Literal(password)
        )
    )


def set_up_roles(conn: psycopg.Connection, roles: Roles) -> None:
    """`agent_ro` reads `public` and nothing else; `api_rw` also reads and writes `app`.

    Neither can see `gt`. Future tables made by the migrating user are granted the same way.
    """
    row = conn.execute("SELECT current_database(), current_user").fetchone()
    assert row is not None
    database, owner = row
    ensure_role(conn, roles.agent, roles.agent_password)
    ensure_role(conn, roles.api, roles.api_password)
    _run(conn, "ALTER ROLE {} SET default_transaction_read_only = on", roles.agent)

    for role in (roles.agent, roles.api):
        _run(conn, "GRANT CONNECT ON DATABASE {} TO {}", database, role)
        _run(conn, "GRANT USAGE ON SCHEMA public TO {}", role)
        _run(conn, "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}", role)
        _run(
            conn,
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}",
            owner,
            role,
        )
        _run(conn, "REVOKE ALL ON SCHEMA gt FROM {}", role)
        _run(conn, "REVOKE ALL ON ALL TABLES IN SCHEMA gt FROM {}", role)

    _run(conn, "REVOKE ALL ON SCHEMA app FROM {}", roles.agent)
    _run(conn, "REVOKE ALL ON ALL TABLES IN SCHEMA app FROM {}", roles.agent)
    _run(conn, "GRANT USAGE ON SCHEMA app TO {}", roles.api)
    _run(conn, "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO {}", roles.api)
    _run(conn, "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {}", roles.api)
    _run(
        conn,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA app "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}",
        owner,
        roles.api,
    )
    _run(
        conn,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO {}",
        owner,
        roles.api,
    )


def copy_data(
    source: psycopg.Connection, target: psycopg.Connection, out: Printer
) -> dict[str, tuple[int, int]]:
    """Empty the target tables, copy every published table, and return (source, target) counts."""
    names = [sql.Identifier("public", t) for t in PUBLISHED_TABLES]
    names.append(sql.Identifier(*GROUND_TRUTH_TABLE))
    with target.transaction():
        target.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(names)))

    counts: dict[str, tuple[int, int]] = {}
    for table in PUBLISHED_TABLES:
        columns = _columns(target, table)
        if columns != _columns(source, table):
            raise PublishError(f"the columns of {table} differ between source and target")
        listing = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
        with (
            target.transaction(),
            source.cursor().copy(
                sql.SQL("COPY {} ({}) TO STDOUT").format(_ident(table), listing)
            ) as reader,
            target.cursor().copy(
                sql.SQL("COPY {} ({}) FROM STDIN").format(_ident(table), listing)
            ) as writer,
        ):
            for block in reader:
                writer.write(block)
        counts[table] = (_count(source, table), _count(target, table))
        out(f"  copied {table}")
    mismatched = [t for t, (a, b) in counts.items() if a != b]
    if mismatched:
        raise PublishError(f"row counts differ for {', '.join(mismatched)}")
    for table in PUBLISHED_TABLES:
        target.execute(sql.SQL("ANALYZE {}").format(_ident(table)))
    return counts


def _source_connection(url: str) -> psycopg.Connection:
    """One repeatable-read, read-only transaction, so every table is read at the same moment."""
    conn = psycopg.connect(libpq_url(url))
    conn.isolation_level = IsolationLevel.REPEATABLE_READ
    conn.read_only = True
    return conn


def publish(
    source_url: str, target_url: str, roles: Roles, *, dry_run: bool, out: Printer = print
) -> None:
    if same_database(source_url, target_url):
        raise PublishError("the target is the source database")
    if is_pooled_host(target_url):
        raise PublishError("the target is a pooled endpoint; use the direct connection string")

    with _source_connection(source_url) as source:
        source_counts = {t: _count(source, t) for t in PUBLISHED_TABLES}
        if dry_run:
            out("Dry run: nothing is sent to the target.")
            out("Steps: alembic upgrade head; roles; empty and copy the tables; compare counts.")
            out(f"Roles: {roles.agent} (read public), {roles.api} (read public, write app)")
            out(f"Tables ({sum(source_counts.values())} rows at the source):")
            for table, n in source_counts.items():
                out(f"  {table:<16}{n:>9}")
            return

        out("Migrating the target to head")
        migrate(target_url)
        with psycopg.connect(libpq_url(target_url), autocommit=True) as target:
            out("Creating roles and grants")
            set_up_roles(target, roles)
            out("Copying tables")
            counts = copy_data(source, target, out)

    out("Rows, source / target:")
    for table, (a, b) in counts.items():
        out(f"  {table:<16}{a:>9}{b:>9}")
    out("Done.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.db.publish")
    parser.add_argument(
        "--target-env",
        required=True,
        help="name of the environment variable (or .env key) holding the target database URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    args = parser.parse_args(argv)

    target = read_setting(args.target_env)
    agent_password = read_setting(AGENT_PASSWORD_VAR)
    api_password = read_setting(API_PASSWORD_VAR)
    missing = [
        name
        for name, value in (
            (args.target_env, target),
            (AGENT_PASSWORD_VAR, agent_password),
            (API_PASSWORD_VAR, api_password),
        )
        if not value
    ]
    if missing:
        print(f"Not set (environment or .env): {', '.join(missing)}", file=sys.stderr)
        return 2
    assert target and agent_password and api_password

    target = with_psycopg_driver(target)
    source = get_settings().database_url
    roles = Roles(AGENT_ROLE, agent_password, API_ROLE, api_password)
    try:
        publish(source, target, roles, dry_run=args.dry_run)
    except Exception as exc:
        secrets = [*secrets_of(source, target), agent_password, api_password]
        print(f"Publish failed: {type(exc).__name__}: {redact(str(exc), secrets)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
