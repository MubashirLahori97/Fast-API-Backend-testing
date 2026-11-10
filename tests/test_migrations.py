from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, text

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.core.database import Base


def test_migrations_match_the_models(engine):
    """Fails when a model changed without a migration.

    Fix: uv run alembic revision --autogenerate -m "describe the change"
    """
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_check_constraints_match_the_models(engine):
    """compare_metadata ignores check constraints, so compare their names here."""
    expected = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    with engine.connect() as connection:
        actual = set(
            connection.scalars(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE c.contype = 'c' AND n.nspname = 'public'"
                )
            )
        )

    assert actual == expected
