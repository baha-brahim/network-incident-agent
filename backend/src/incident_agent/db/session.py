"""SQLAlchemy engine and session factory, built from settings."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from incident_agent.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


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
