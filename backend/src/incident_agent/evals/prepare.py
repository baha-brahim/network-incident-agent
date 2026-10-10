"""Prepare the database of an evaluation world.

One database per seed on the same server (`incident_agent_eval_s<seed>`; seed 42 is the dev
database). Preparation creates it, grants the read-only role, migrates it, builds and loads the
world, runs the detector and ingests the runbooks. Every stage is skipped when it is already
done, so the command can be repeated.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from incident_agent.config import REPO_ROOT, Settings, get_settings
from incident_agent.db.loader import LOAD_ORDER, load_world, qualified_name
from incident_agent.detector.store import run_detector
from incident_agent.evals.cases import DEV_SEED
from incident_agent.rag.embedder import Embedder
from incident_agent.rag.ingest import ingest
from incident_agent.simulator.build import build_world
from incident_agent.simulator.world import World

ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"
EVAL_DB_PREFIX = "incident_agent_eval_s"
AGENT_RO = "agent_ro"
AGENT_RO_PASSWORD = "agent_ro"  # local dev role, as created by docker/postgres/init.sql


@dataclass(frozen=True)
class DbTargets:
    name: str
    owner_url: URL  # migrations, loading, ground truth
    agent_url: URL  # what the agent's tools connect with (read-only role)
    admin_url: URL  # a database to connect to for CREATE DATABASE


def resolve_targets(
    seed: int, *, database: str | None = None, settings: Settings | None = None
) -> DbTargets:
    """The databases of a seed: seed 42 is the dev database, every other seed has its own."""
    cfg = settings or get_settings()
    dev = make_url(cfg.database_url)
    name = database or (dev.database if seed == DEV_SEED else f"{EVAL_DB_PREFIX}{seed}")
    if not name:
        raise ValueError("DATABASE_URL names no database")
    return DbTargets(
        name=name,
        owner_url=dev.set(database=name),
        agent_url=make_url(cfg.agent_db_url).set(database=name),
        admin_url=dev,
    )


def url_string(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@dataclass
class PrepareReport:
    database: str
    created: bool = False
    world_loaded: bool = False
    detector_run: bool = False
    rows: dict[str, int] = field(default_factory=dict)
    alerts: int = 0
    anomalies: int = 0
    runbook_docs: int = 0
    runbook_chunks: int = 0
    seconds: dict[str, float] = field(default_factory=dict)


def ensure_database(targets: DbTargets) -> bool:
    """Create the database if missing and let the read-only role connect. True if created."""
    admin = create_engine(targets.admin_url, isolation_level="AUTOCOMMIT")
    owner_name = targets.owner_url.username or "incident"
    try:
        with admin.connect() as conn:
            quote = admin.dialect.identifier_preparer.quote
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": targets.name}
            ).scalar()
            if not exists:
                conn.execute(text(f"CREATE DATABASE {quote(targets.name)}"))
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS "
                    f"(SELECT 1 FROM pg_roles WHERE rolname = '{AGENT_RO}') THEN "
                    f"CREATE ROLE {AGENT_RO} LOGIN PASSWORD '{AGENT_RO_PASSWORD}'; "
                    "END IF; END $$"
                )
            )
            conn.execute(text(f"ALTER ROLE {AGENT_RO} SET default_transaction_read_only = on"))
            conn.execute(text(f"GRANT CONNECT ON DATABASE {quote(targets.name)} TO {AGENT_RO}"))
            _grant_usage(targets, quote(owner_name))
        return not exists
    finally:
        admin.dispose()


def _grant_usage(targets: DbTargets, owner: str) -> None:
    engine = create_engine(targets.owner_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {AGENT_RO}"))
            conn.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
                    f"GRANT SELECT ON TABLES TO {AGENT_RO}"
                )
            )
    finally:
        engine.dispose()


def migrate(targets: DbTargets) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url_string(targets.owner_url).replace("%", "%%"))
    command.upgrade(cfg, "head")
    engine = create_engine(targets.owner_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {AGENT_RO}"))
    finally:
        engine.dispose()


def loaded_seed(engine: Engine) -> str | None:
    """The seed of the world in the database, or None when no world is loaded."""
    with engine.connect() as conn:
        value = conn.execute(text("SELECT value FROM dataset_meta WHERE key = 'seed'")).scalar()
        n_nodes = conn.execute(text("SELECT count(*) FROM nodes")).scalar_one()
    return str(value) if value is not None and n_nodes else None


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def prepare_database(
    targets: DbTargets,
    seed: int,
    *,
    force: bool = False,
    world_builder: Callable[[int], World] = build_world,
    embedder: Embedder | None = None,
    log: Callable[[str], None] = print,
) -> PrepareReport:
    """Bring `targets` to the state an evaluation needs. No model is called."""
    report = PrepareReport(database=targets.name)

    def stage[T](label: str, fn: Callable[[], T]) -> T:
        started = time.perf_counter()
        out = fn()
        report.seconds[label] = round(time.perf_counter() - started, 2)
        log(f"  {label}: {report.seconds[label]:.1f}s")
        return out

    log(f"preparing {targets.name} for seed {seed}")
    report.created = stage("database and grants", lambda: ensure_database(targets))
    stage("migrations", lambda: migrate(targets))
    engine = create_engine(targets.owner_url)
    try:
        current = loaded_seed(engine)
        if current is not None and current != str(seed) and not force:
            raise RuntimeError(
                f"{targets.name} holds the world of seed {current}, not {seed}; "
                "use another --database, or --force to replace it."
            )
        if force or current is None:
            world = stage("build world", lambda: world_builder(seed))
            counts = stage("load world", lambda: load_world(world, engine))
            report.world_loaded = True
            log("  rows: " + ", ".join(f"{t} {n:,}" for t, n in counts.items()))
        if report.world_loaded or _count(engine, "alerts") == 0:
            stage("detector", lambda: run_detector(engine))
            report.detector_run = True
        ingested = stage("runbooks", lambda: ingest(engine=engine, embedder=embedder))
        log(f"  runbooks: {ingested.n_docs} documents, {ingested.n_chunks} chunks")
        report.rows = {t: _count(engine, qualified_name(t)) for t in LOAD_ORDER}
        report.alerts = _count(engine, "alerts")
        report.anomalies = _count(engine, "anomalies")
        report.runbook_docs = _count(engine, "runbook_docs")
        report.runbook_chunks = _count(engine, "runbook_chunks")
    finally:
        engine.dispose()
    return report
