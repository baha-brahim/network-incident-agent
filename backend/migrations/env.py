from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from incident_agent.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# M2 will point this at the declarative Base metadata.
target_metadata = None


def database_url() -> str:
    """An explicit `sqlalchemy.url` (e.g. set by the test suite) wins; settings are the fallback."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
