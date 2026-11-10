from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# hide_parameters keeps query values (which can be health data) out of error messages and logs.
# READ COMMITTED is Postgres's default, pinned because the row-lock checks rely on it: a count
# run after taking a lock sees what the request that held the lock committed.
engine = create_engine(
    settings.database_url, hide_parameters=True, isolation_level="READ COMMITTED"
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Every table class inherits from Base, so Base.metadata knows about all of them.
class Base(DeclarativeBase):
    # Store every datetime column as timestamptz, so times are never ambiguous.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request, closed afterwards."""
    with SessionLocal() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]
