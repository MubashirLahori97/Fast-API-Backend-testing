import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Kept in step with kinds.CATEGORY_LABELS.
_CATEGORY_CHECK = (
    "category IN ('support_requests', 'knowledge_gaps', 'deletion_requests', "
    "'deletion_deadlines', 'knowledge_base', 'policies', 'admins')"
)


class AdminNotification(Base):
    """One notice in an Admin's or the Super Admin's notification centre (Super Admin 11.1).
    Each recipient gets their own row, so read state is theirs. The email copy is sent from it
    by a job (app/admin/notifications/jobs.py), with the kind's general text only.

    The body can hold a knowledge gap's question (11.1: "a new knowledge gap, with the
    question"), which the gap itself shows to the team too; never a Client's name or email."""

    __tablename__ = "admin_notifications"
    __table_args__ = (
        Index("ix_admin_notifications_recipient_created", "recipient_id", "created_at"),
        Index(
            "ix_admin_notifications_recipient_unread",
            "recipient_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str]  # a key of KINDS in app/admin/notifications/kinds.py
    title: Mapped[str]
    body: Mapped[str]
    email_text: Mapped[str]  # what the email says: no Client or health details
    # Where opening it goes: a Screen in kinds.py, plus the record it opens. No foreign key:
    # the record lives in another package's table, and may be resolved or gone.
    screen: Mapped[str]
    target_id: Mapped[uuid.UUID | None]
    read_at: Mapped[datetime | None]
    # clock_timestamp(): several made in one transaction still sort in order.
    created_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))


class AdminNotificationPreference(Base):
    """An Admin's email choice for one type (Super Admin 11.1). A missing row means email on.
    In-app notifications are always on, and the deletion deadline type can't be turned off,
    so only the types that can be are stored."""

    __tablename__ = "admin_notification_preferences"
    __table_args__ = (
        UniqueConstraint("account_id", "category"),
        CheckConstraint(_CATEGORY_CHECK, name="ck_admin_notification_preferences_category"),
        CheckConstraint(
            "category <> 'deletion_deadlines'",
            name="ck_admin_notification_preferences_not_locked",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str]
    email: Mapped[bool]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
