import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.core.database import Base
from app.profiles.models import Profile


class SupportRequest(Base):
    """A request for the support team (story 10.1), which appears in their list (Super Admin
    story 5.1). Kinds:

    - talk_to_support: "Talk to the Support Team", from the Contact support team form, or from
      a conversation when the client asks for a person and agrees to send a message;
    - consultation: a "Consultation Request" from the Consult with support team form. Any
      consultation is booked and paid outside the app, so nothing about bookings is kept;
    - knowledge_gap: a question the Oracle couldn't answer, sent from a conversation with the
      client's agreement. Phase A builds Super Admin 6.3's knowledge gap listing from these;
    - email_change: an "Email Change Request" from Profile & Account (story 11.1), with the
      address the client asked for in `requested_email` and an empty message. The team changes
      the address in the admin panel (accounts.service.change_email), which resolves it.

    The message, and the team's internal notes, can describe the client's health: they're
    health data, stored in plain text until Phase 4 adds field encryption (docs/PLAN.md),
    and never logged, audited, or put in emails or job payloads. The client's first name,
    email and account type are read from the account when the team opens the request, so
    they're always current."""

    __tablename__ = "support_requests"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('talk_to_support', 'consultation', 'knowledge_gap', 'email_change')",
            name="ck_support_requests_kind",
        ),
        # An email change comes from its form, and is the only kind with a requested address.
        CheckConstraint(
            "(kind = 'email_change') = (requested_email IS NOT NULL)",
            name="ck_support_requests_requested_email",
        ),
        CheckConstraint(
            "kind <> 'email_change' OR source = 'form'",
            name="ck_support_requests_email_change_source",
        ),
        # Story 11.1: one email change request pending at a time.
        Index(
            "uq_support_requests_one_open_email_change",
            "account_id",
            unique=True,
            postgresql_where=text("kind = 'email_change' AND status = 'open'"),
        ),
        CheckConstraint("status IN ('open', 'resolved')", name="ck_support_requests_status"),
        CheckConstraint("source IN ('form', 'conversation')", name="ck_support_requests_source"),
        # A consultation comes only from its form, and a knowledge gap only from the Oracle.
        CheckConstraint(
            "kind <> 'consultation' OR source = 'form'",
            name="ck_support_requests_consultation_source",
        ),
        CheckConstraint(
            "kind <> 'knowledge_gap' OR source = 'conversation'",
            name="ck_support_requests_knowledge_gap_source",
        ),
        # A form request carries the app's id for it; a conversation request, its conversation.
        CheckConstraint(
            "(source = 'form') = (client_request_id IS NOT NULL)",
            name="ck_support_requests_client_request_id",
        ),
        CheckConstraint(
            "source = 'conversation' OR (conversation_id IS NULL AND source_message_id IS NULL)",
            name="ck_support_requests_form_fields",
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name="ck_support_requests_resolved_at",
        ),
        # A resend after a lost connection, or once the app is back online, finds the
        # request it already saved.
        UniqueConstraint("account_id", "client_request_id"),
        # Agreeing twice to send the same question sends it once.
        Index(
            "uq_support_requests_source_message_kind",
            "source_message_id",
            "kind",
            unique=True,
            postgresql_where=text("source_message_id IS NOT NULL"),
        ),
        # The per-account hourly limit counts recent requests.
        Index("ix_support_requests_account_created", "account_id", "created_at"),
        # The team's list: open requests first, oldest first (Super Admin story 5.1).
        Index("ix_support_requests_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Deleted with the account: the message is health data, so it doesn't outlive it. The
    # audit events (kind and id only) stay.
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The profile it's about ("Sent by Sarah about Azka"): the active profile when it was
    # sent. Null when the client had no profile yet, or once that profile's data is deleted.
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str]  # talk_to_support | consultation | knowledge_gap | email_change
    source: Mapped[str]  # form | conversation
    status: Mapped[str] = mapped_column(default="open", server_default="open")  # or resolved
    # What the client wrote in the form, or the message from the conversation: for a
    # knowledge gap, the question the Oracle couldn't answer. Copied, so it stays readable
    # if the conversation is deleted.
    message: Mapped[str]

    # Form requests: the id the app made for this request, sent again with any retry.
    client_request_id: Mapped[uuid.UUID | None]
    # Email change requests (story 11.1): the new address, lowercase like users.email.
    requested_email: Mapped[str | None]
    # Conversation requests: where it came from. Kept apart from the copied message, so a
    # purged conversation leaves the request in place.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )

    # The team's side (Super Admin story 5.1). The notes are free text, so health data too.
    internal_notes: Mapped[str | None]
    # When the email to the support team went out (story 10.1: within 1 minute).
    team_notified_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    account: Mapped[User] = relationship(foreign_keys=[account_id])
    profile: Mapped[Profile | None] = relationship()
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])
