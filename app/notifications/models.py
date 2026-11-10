import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """One notice in the client's notification centre (story 12.1). Push and email copies are
    sent from it by jobs (app/notifications/jobs.py), with general text only.

    The title and body hold no health data: [topic] and [specialty] stay as placeholders and are
    filled from the linked record when the list is shown (app/notifications/targets.py). They
    can hold a family member's first name, which only the owning account sees; deleting the
    profile deletes its notifications."""

    __tablename__ = "notifications"
    __table_args__ = (
        # The list, newest first, and the bell's unread count.
        Index("ix_notifications_account_created", "account_id", "created_at"),
        Index(
            "ix_notifications_account_unread",
            "account_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The profile it's about, which the app switches to when it's opened. Null for notices
    # about the account (billing, inactivity, teens with their own account).
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str]  # a key of KINDS in app/notifications/kinds.py
    title: Mapped[str]
    body: Mapped[str]
    # What its push and email copies say: never a name or health detail (12.1).
    outside_text: Mapped[str]
    # Where tapping it goes: a Screen in kinds.py, plus the record it opens, if any. No foreign
    # key: the record lives in another phase's table, and may be deleted (12.1's "This item is
    # no longer available.").
    screen: Mapped[str]
    target_id: Mapped[uuid.UUID | None]
    read_at: Mapped[datetime | None]
    # clock_timestamp(), not now(): two notices made in one transaction still sort in order.
    created_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))


class NotificationPreference(Base):
    """The client's choice for one notification type (story 12.1). Only the types the client
    can turn off are stored; a missing row means the defaults (on, by push, and by email when
    settings.notification_email_by_default). They apply to every device of the account."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("account_id", "category"),
        CheckConstraint(
            "category IN ('guidance_follow_ups', 'appointments', 'wellness_plan', "
            "'health_profile', 'inactivity')",
            name="ck_notification_preferences_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str]
    enabled: Mapped[bool]
    # Kept while the type is off, so turning it back on restores the choice.
    push: Mapped[bool]
    email: Mapped[bool]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PushToken(Base):
    """A device that receives push notifications: the Mobile App registers its token after
    sign-in, if the client allows notifications (story 12.1).

    The provider needs the token itself to send, so it can't be stored only as a hash. It's
    personal data (it identifies a device), never returned by the API or logged, and gets the
    Phase 4 field encryption; `token_hash` is what lookups and the unique index use, so they
    keep working once `token` is encrypted.

    It belongs to the session that registered it. Pushes go to it while that session is active
    or has only timed out; once the device signs out, or every session ends (a password reset,
    a policy update), it gets none until it signs in and registers again."""

    __tablename__ = "push_tokens"
    __table_args__ = (
        CheckConstraint("platform IN ('ios', 'android')", name="ck_push_tokens_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str]  # ios | android
    token: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Registering the same token again (after each sign-in) moves it to the new session.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
