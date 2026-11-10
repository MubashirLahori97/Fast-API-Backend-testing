"""Background jobs for notifications and policy updates, run by app/worker.py.

Payloads carry ids only (plus a scheduled reminder's options, such as "6 months"). The worker
commits after each handler.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.accounts.models import PolicyVersion
from app.core.config import settings
from app.core.email import get_email_sender
from app.core.jobs import Job
from app.core.push import get_push_sender
from app.notifications import service
from app.worker import handles, on_startup


@handles(service.SEND_JOB)
def send_scheduled(db: Session, payload: dict[str, Any]) -> None:
    """A reminder another phase scheduled with service.schedule()."""
    service.send_scheduled(db, payload)


@handles(service.PUSH_JOB)
def send_push(db: Session, payload: dict[str, Any]) -> None:
    service.deliver_push(db, payload, get_push_sender())


@handles(service.EMAIL_JOB)
def send_email(db: Session, payload: dict[str, Any]) -> None:
    service.deliver_email(db, payload, get_email_sender())


@handles(service.SWEEP_JOB)
def sweep(db: Session, payload: dict[str, Any]) -> None:
    """Trial reminders and inactivity check-ins (12.1), every settings.reminder_sweep_seconds.

    The next run is saved before this one does any work, so a failure here doesn't stop the
    sweeps, and this kind's finished rows are removed, so a run a minute doesn't fill the jobs
    table."""
    now = datetime.now(UTC)
    db.execute(delete(Job).where(Job.kind == service.SWEEP_JOB, Job.status == "done"))
    service.ensure_sweep(db, run_at=now + timedelta(seconds=settings.reminder_sweep_seconds))
    db.commit()
    service.run_sweep(db, now)


@on_startup
def start_sweep(db: Session) -> None:
    """The first sweep, or a new one if the chain broke (say, after a failed run)."""
    service.ensure_sweep(db)
    db.commit()


@handles(service.ANNOUNCE_POLICY_JOB)
def announce_policy_version(db: Session, payload: dict[str, Any]) -> None:
    """A policy version published with a future date takes effect now (story 12.2)."""
    policy = db.get(PolicyVersion, uuid.UUID(payload["policy_version_id"]))
    if policy is not None:
        accounts.announce_policy_version(db, policy)


@handles(service.POLICY_EMAILS_JOB)
def queue_policy_update_emails(db: Session, payload: dict[str, Any]) -> None:
    service.queue_policy_update_emails(db, payload)


@handles(service.POLICY_EMAIL_JOB)
def send_policy_update_email(db: Session, payload: dict[str, Any]) -> None:
    service.send_policy_update_email(db, payload, get_email_sender())
