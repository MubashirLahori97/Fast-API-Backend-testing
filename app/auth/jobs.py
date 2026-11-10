"""Background jobs for sign-up, run by app/worker.py."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth.models import PendingSignUp, VerificationChallenge
from app.auth.service import PURGE_PENDING_SIGN_UP_JOB
from app.core import jobs
from app.worker import handles


@handles(PURGE_PENDING_SIGN_UP_JOB)
def purge_pending_sign_up(db: Session, payload: dict[str, Any]) -> None:
    """Story 1.1: a sign-up whose code is never verified doesn't become an account, so its
    details (date of birth, state, password hash) are deleted once it expires.

    Each run deletes every expired attempt, not only its own, so one job that failed or was
    lost doesn't leave details behind. If its own attempt was kept longer (a new code), it
    runs again then. The worker commits."""
    now = datetime.now(UTC)
    # Their codes are left closed, with no owner (ON DELETE SET NULL), to answer "request a
    # new code" for a while; after a day they go too.
    db.execute(delete(PendingSignUp).where(PendingSignUp.expires_at <= now))
    db.execute(
        delete(VerificationChallenge).where(
            VerificationChallenge.user_id.is_(None),
            VerificationChallenge.pending_sign_up_id.is_(None),
            VerificationChallenge.created_at < now - timedelta(days=1),
        )
    )
    pending = db.get(PendingSignUp, uuid.UUID(payload["pending_sign_up_id"]))
    if pending is not None:
        jobs.enqueue(db, PURGE_PENDING_SIGN_UP_JOB, payload, run_at=pending.expires_at)
