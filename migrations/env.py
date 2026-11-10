from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.core.config import settings
from app.core.database import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False keeps the app's loggers working when tests run migrations.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# The tests pass their own database in config.attributes; otherwise use the app's settings.
database_url = config.attributes.get("database_url", settings.database_url)


def run_migrations_offline() -> None:
    """Print the SQL instead of running it: uv run alembic upgrade head --sql"""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
