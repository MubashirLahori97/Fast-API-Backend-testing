import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeletionReview(Base):
    """The support team's side of a deletion request (Super Admin 5.2), kept beside the
    privacy package's `deletion_requests` row: the review checklist, the internal notes, the
    legal hold note, the date a teen's email was received (for a request the team created), and
    when the team was reminded of the deadline.

    Kept as long as the request is, which outlives the data it deleted, so the notes must hold
    no health information: the admin panel says so beside the field. Never logged or audited."""

    __tablename__ = "deletion_request_reviews"

    deletion_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deletion_requests.id", ondelete="CASCADE"), primary_key=True
    )
    # The review checklist: identity confirmed, legal hold checked.
    identity_confirmed: Mapped[bool] = mapped_column(default=False, server_default="false")
    legal_hold_checked: Mapped[bool] = mapped_column(default=False, server_default="false")
    internal_notes: Mapped[str | None]
    legal_hold_note: Mapped[str | None]
    # A Teen Deletion created from an email: the day it was received. The deadline counts from
    # it.
    email_received_on: Mapped[date | None]
    # Super Admin 11.1's reminder, 5 days before the 45-day deadline, sent once.
    deadline_reminded_at: Mapped[datetime | None]
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
