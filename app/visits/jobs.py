"""Background jobs for logged visits (story 5.2), run by app/worker.py. Payloads hold the visit
log's id and revision only."""

from typing import Any

from sqlalchemy.orm import Session

from app.oracle.dependencies import get_oracle
from app.visits.service import REVIEW_JOB, review_visit
from app.worker import handles


@handles(REVIEW_JOB)
def review(db: Session, payload: dict[str, Any]) -> None:
    """The Oracle's review of one save of a visit log (app/visits/service.py)."""
    review_visit(db, payload, get_oracle())
