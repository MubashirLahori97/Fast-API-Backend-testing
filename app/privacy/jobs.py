"""Background jobs for Privacy & Data (story 11.4), run by app/worker.py. Payloads hold a
deletion request's id only. The worker commits after each handler."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email import get_email_sender
from app.core.jobs import Job
from app.privacy import purge, service
from app.worker import handles, on_startup


def _request_id(payload: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(payload["deletion_request_id"])


@handles(service.NOTIFY_TEAM_JOB)
def notify_team(db: Session, payload: dict[str, Any]) -> None:
    """Super Admin 5.2: the team is told about each request once its grace period ends (type,
    id and deadline only)."""
    service.notify_team(db, _request_id(payload), get_email_sender().send)


@handles(service.PURGE_JOB)
def purge_request(db: Session, payload: dict[str, Any]) -> None:
    """Deletes the data of a request the team completed. Retried if it fails; a request that
    went on legal hold meanwhile is left alone. The emails to invited teens (and to the parent
    for an Invited Teen Removal) go once the deletion is committed: their accounts are gone, so
    no job could find their addresses later. If sending fails, the purge isn't run again."""
    later = purge.purge_request(db, _request_id(payload))
    db.commit()
    sender = get_email_sender()
    for message in later:
        sender.send(message)


@handles(service.COMPLETION_EMAIL_JOB)
def completion_email(db: Session, payload: dict[str, Any]) -> None:
    purge.send_completion_email(db, _request_id(payload), get_email_sender().send)


@handles(service.SWEEP_JOB)
def sweep(db: Session, payload: dict[str, Any]) -> None:
    """Every settings.privacy_sweep_minutes: the grace period reminders, the end of grace
    periods (the lock, Pending review, the team told), a safety net for team emails, and the
    purge of conversations clients deleted.

    The next run is saved before this one does any work, so a failure doesn't stop the chain,
    and this kind's finished rows are removed."""
    now = datetime.now(UTC)
    db.execute(delete(Job).where(Job.kind == service.SWEEP_JOB, Job.status == "done"))
    service.ensure_sweep(db, run_at=now + timedelta(minutes=settings.privacy_sweep_minutes))
    db.commit()
    service.send_grace_reminders(db, now)
    service.end_grace_periods(db, now)
    service.queue_team_emails(db, now)
    purge.purge_deleted_conversations(db, now)


@on_startup
def start_sweep(db: Session) -> None:
    """The first sweep, or a new one if the chain broke."""
    service.ensure_sweep(db)
    db.commit()
