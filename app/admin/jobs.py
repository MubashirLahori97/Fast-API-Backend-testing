"""Background jobs for the admin panel's operations, run by app/worker.py.

- `admin.sweep`, every `settings.admin_sweep_seconds`: takes in new Knowledge Gap support
  requests as knowledge gaps (Super Admin 6.3: within 1 minute), and reminds the team of
  deletion requests close to their deadline (11.1). It queues its own next run first and
  deletes its finished rows, like the notifications sweep.
- The price change emails to existing subscribers (8.1).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin.deletions import service as deletions
from app.admin.plans import service as plans
from app.core import jobs
from app.core.config import settings
from app.core.email import get_email_sender
from app.core.jobs import Job
from app.knowledge import service as knowledge
from app.oracle.dependencies import get_oracle
from app.worker import handles, on_startup

SWEEP_JOB = "admin.sweep"
# Key for pg_advisory_xact_lock, so two workers starting at once don't both start a sweep.
SWEEP_LOCK_KEY = 9_120_410


def ensure_sweep(db: Session, run_at: datetime | None = None) -> None:
    """Makes sure one admin sweep is waiting to run. The caller commits."""
    db.execute(select(func.pg_advisory_xact_lock(SWEEP_LOCK_KEY)))
    waiting = db.scalar(
        select(Job.id).where(Job.kind == SWEEP_JOB, Job.status == "pending").limit(1)
    )
    if waiting is None:
        jobs.enqueue(db, SWEEP_JOB, run_at=run_at)


@handles(SWEEP_JOB)
def sweep(db: Session, payload: dict[str, Any]) -> None:
    now = datetime.now(UTC)
    db.execute(delete(Job).where(Job.kind == SWEEP_JOB, Job.status == "done"))
    ensure_sweep(db, run_at=now + timedelta(seconds=settings.admin_sweep_seconds))
    db.commit()  # the next run is queued even if this one fails
    knowledge.take_in_new_gaps(db, get_oracle())
    deletions.send_deadline_reminders(db)


@on_startup
def start_sweep(db: Session) -> None:
    """The first sweep, or a new one if the chain broke."""
    ensure_sweep(db)
    db.commit()


@handles(plans.PRICE_CHANGE_JOB)
def queue_price_change_emails(db: Session, payload: dict[str, Any]) -> None:
    plans.queue_price_change_emails(db, payload)


@handles(plans.PRICE_CHANGE_EMAIL_JOB)
def send_price_change_email(db: Session, payload: dict[str, Any]) -> None:
    plans.send_price_change_email(db, payload, get_email_sender().send)
