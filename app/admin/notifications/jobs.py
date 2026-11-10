"""Background jobs for admin notifications, run by app/worker.py. The payload is the
notification's id only; the worker commits."""

from typing import Any

from sqlalchemy.orm import Session

from app.admin.notifications import service
from app.core.email import get_email_sender
from app.worker import handles


@handles(service.EMAIL_JOB)
def send_email(db: Session, payload: dict[str, Any]) -> None:
    """Super Admin 11.1: the email copy, within a minute (the worker polls every few seconds).
    If sending fails, the worker tries again; the notice stays in the notification centre."""
    service.deliver_email(db, payload, get_email_sender())
