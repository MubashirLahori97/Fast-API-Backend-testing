"""Background jobs for teens with their own account (story 1.6), run by app/worker.py. The age
check's payload is empty."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.jobs import Job
from app.teens import service
from app.worker import handles, on_startup


@handles(service.AGE_CHECK_JOB)
def age_check(db: Session, payload: dict[str, Any]) -> None:
    """Story 1.6's daily age check. The next run is saved before this one does any work, so a
    failure doesn't stop the chain, and this kind's finished rows are removed."""
    db.execute(delete(Job).where(Job.kind == service.AGE_CHECK_JOB, Job.status == "done"))
    service.ensure_age_check(db, run_at=service.next_age_check_at())
    db.commit()
    service.run_age_check(db, datetime.now(UTC))


@on_startup
def start_age_check(db: Session) -> None:
    """The first age check (straight away), or a new one if the chain broke."""
    service.ensure_age_check(db)
    db.commit()
