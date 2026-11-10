"""Background jobs for support requests, run by app/worker.py."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email import get_email_sender
from app.support import emails
from app.support.models import SupportRequest
from app.support.service import NOTIFY_TEAM_JOB
from app.worker import handles


@handles(NOTIFY_TEAM_JOB)
def notify_team(db: Session, payload: dict[str, Any]) -> None:
    """Story 10.1: every request reaches the support email within 1 minute. The job is due as
    soon as the request is saved, and the worker polls every few seconds. The email names
    only the type and the id. If sending fails, the worker tries again; the worker commits."""
    support_request = db.get(
        SupportRequest, uuid.UUID(payload["support_request_id"]), with_for_update=True
    )
    if support_request is None or support_request.team_notified_at is not None:
        return  # deleted with its account, or already sent
    get_email_sender().send(emails.new_request(settings.support_team_email, support_request))
    support_request.team_notified_at = datetime.now(UTC)
