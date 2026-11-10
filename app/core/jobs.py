"""Background jobs: rows in the `jobs` table that app/worker.py picks up and runs.

Payloads hold ids and options only, never health data or secrets.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_at", "status", "run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str]  # names the handler that runs it, e.g. "send_email"
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(default="pending")  # pending | running | done | failed
    run_at: Mapped[datetime] = mapped_column(server_default=func.now())
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
) -> Job:
    """Add a job to the session. It's saved when the caller commits, so it only runs if the
    caller's own changes were saved too."""
    job = Job(kind=kind, payload=payload or {})
    if run_at is not None:
        job.run_at = run_at
    db.add(job)
    return job


def claim_next(db: Session) -> Job | None:
    """Lock the next due job and mark it running. SKIP LOCKED lets several workers share the
    table without picking the same job."""
    stmt = (
        select(Job)
        .where(Job.status == "pending", Job.run_at <= func.now())
        .order_by(Job.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.scalars(stmt).first()
    if job is not None:
        job.status = "running"
        job.attempts += 1
    return job
