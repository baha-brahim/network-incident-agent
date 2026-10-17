"""SQLAlchemy engine and session factory, built from settings."""

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from incident_agent.config import get_settings

# A Lambda instance serves one request at a time, so a small pool is enough; Neon's connection
# limit is shared by every instance.
POOL_SIZE = 2
MAX_OVERFLOW = 2
POOL_RECYCLE_SECONDS = 300


def is_pooled_host(url: str) -> bool:
    """Neon's pooled endpoint (`<endpoint>-pooler.<region>...`) runs PgBouncer."""
    return "-pooler" in (make_url(url).host or "")


def build_engine(url: str) -> Engine:
    """A small pool that checks connections before use.

    Behind PgBouncer in transaction mode, consecutive statements may run on different server
    connections, so psycopg must not keep server-side prepared statements.
    """
    connect_args: dict[str, Any] = {"prepare_threshold": None} if is_pooled_host(url) else {}
    return create_engine(
        url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=POOL_RECYCLE_SECONDS,
        connect_args=connect_args,
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


@lru_cache
def get_agent_engine() -> Engine:
    """Read-only engine (role agent_ro) used by every agent tool. It can't write or read `gt`."""
    return build_engine(get_settings().agent_db_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def check_connection(engine: Engine | None = None) -> None:
    """Run SELECT 1 and verify the pgvector extension is installed. Raises on failure."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        has_vector = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    if not has_vector:
        raise RuntimeError(
            "Connected, but the 'vector' extension is missing; run `alembic upgrade head`"
        )
