"""Background jobs for the Wellness Plan (story 7.1), run by app/worker.py. Payloads hold ids
only (and a visit log's revision)."""

from typing import Any

from sqlalchemy.orm import Session

from app.oracle.dependencies import get_oracle
from app.wellness.triggers import UPDATE_JOB
from app.wellness.updates import run_update
from app.worker import handles


@handles(UPDATE_JOB)
def update_plan(db: Session, payload: dict[str, Any]) -> None:
    """Creates or updates one profile's plan from one new item (app/wellness/updates.py)."""
    run_update(db, payload, get_oracle())
