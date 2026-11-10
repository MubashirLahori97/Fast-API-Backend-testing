import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EscalationNote(Base):
    """The reviewer's notes on an escalation (Super Admin 4.1), for example a possible false
    alarm. Free text that can describe the client's health, so it's kept apart from the
    escalation record (which outlives every deletion for 6 years and holds no health data) and
    is deleted with the client's account. Never logged or audited: the audit event says a note
    was saved, not what it says."""

    __tablename__ = "escalation_notes"

    escalation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("escalations.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    notes: Mapped[str]
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
