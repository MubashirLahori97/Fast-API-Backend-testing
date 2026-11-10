import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.profiles.models import Profile


class Conversation(Base):
    """A conversation with the Oracle about one profile (story 3.1). Each profile has its own
    conversations; switching profile opens that profile's list.

    The topic and every message are health data: stored in plain text until Phase 4 adds field
    encryption (docs/PLAN.md), and never logged."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_profile_last_message", "profile_id", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    # Written by the Oracle after its first reply, e.g. "waking at 3am".
    topic: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_message_at: Mapped[datetime]
    # Deleted by the client: gone from every list and lookup straight away. The messages stay
    # until Phase 10's purge, which also knows what the law makes us keep (docs/PLAN.md).
    deleted_at: Mapped[datetime | None]

    profile: Mapped[Profile] = relationship()


class Message(Base):
    """One message from the client or the Oracle, saved as it's sent (story 3.1)."""

    __tablename__ = "messages"
    __table_args__ = (
        # A resend after a lost connection finds the message it already saved.
        UniqueConstraint("conversation_id", "client_msg_id"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        CheckConstraint("role IN ('client', 'oracle')", name="ck_messages_role"),
        # Client messages carry the app's id, their safety check and their reply attempts;
        # Oracle messages carry their widgets and the message they answer.
        CheckConstraint(
            "(role = 'client') = (client_msg_id IS NOT NULL)", name="ck_messages_client_msg_id"
        ),
        CheckConstraint(
            "role = 'client' OR (safety_level IS NULL AND answer IS NULL "
            "AND reply_started_at IS NULL AND reply_attempts = 0)",
            name="ck_messages_client_fields",
        ),
        CheckConstraint(
            "role = 'oracle' OR (reply_to_id IS NULL AND widgets IS NULL)",
            name="ck_messages_oracle_fields",
        ),
        CheckConstraint(
            "safety_level IN ('none', 'urgent', 'emergency', 'crisis')",
            name="ck_messages_safety_level_values",
        ),
        # Story 3.2's fields are client messages' too.
        CheckConstraint(
            "role = 'client' OR (safety_reason IS NULL AND NOT outside_us)",
            name="ck_messages_safety_fields",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str]  # client | oracle
    text: Mapped[str]

    # Client messages:
    # the id the app made for it;
    client_msg_id: Mapped[uuid.UUID | None]
    # what they tapped in reply to a widget (see Answer in app/oracle/contract.py);
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # the Oracle's safety check (story 3.2): null until a check succeeds, and no reply is
    # given until then;
    safety_level: Mapped[str | None]
    # the check's one-line reason, for the support team's review (Super Admin story 4.1). Health
    # data, so it's kept here, deleted with the message, and never in the escalation record;
    safety_reason: Mapped[str | None]
    # the app says the device is outside the US (story 3.2), so the safety advice gives the
    # local emergency number instead of 911 and 988. False when the location is unknown;
    outside_us: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # when a reply stream last claimed it, and how many times one has (see reply_events).
    reply_started_at: Mapped[datetime | None]
    reply_attempts: Mapped[int] = mapped_column(default=0, server_default="0")

    # Oracle messages:
    # the client message they answer (each gets at most one), or null for lines the Oracle
    # opens with, such as "How are you feeling today?";
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    # the structured parts the apps render with the text (see Widget in app/oracle/contract.py).
    widgets: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    # clock_timestamp(), not now(): two messages saved in one transaction still sort in order.
    created_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))


class MessageFeedback(Base):
    """A thumbs up or down on one of the Oracle's replies, with an optional comment. The 4 Nov
    stories don't ask for it (docs/PLAN.md lists the assumptions). The comment can describe
    the client's health, so it's health data: plain text until Phase 4, never logged."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # One per reply: giving it again replaces it.
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    given_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[str]  # up | down
    comment: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Escalation(Base):
    """An urgent, emergency or crisis concern the safety check found in a client message (story
    3.2), recorded for the support team to review (Super Admin story 4.1). Nobody contacts the
    client about it.

    Kept for at least `settings.escalation_retention_years` (BAA Section 13), so it outlives
    the conversation, its messages, the profile and the account: plain ids with no foreign keys,
    like `deletion_requests` and the audit log, and nothing is deleted along with them. It holds
    no message text: the triggering message, the check's reason and the advice line shown are
    found by id while they still exist (`messages.safety_reason`).

    An emergency or a crisis opens a safety hold on the conversation until the client picks an
    option (`client_choice`): no reply is given until then (app/conversations/safety.py)."""

    __tablename__ = "escalations"
    __table_args__ = (
        CheckConstraint("level IN ('urgent', 'emergency', 'crisis')", name="ck_escalations_level"),
        CheckConstraint(
            "profile_type IN ('self', 'family_member', 'teen')", name="ck_escalations_profile_type"
        ),
        CheckConstraint(
            "client_choice IN ('called_for_help', 'reached_out', 'safe_now')",
            name="ck_escalations_client_choice",
        ),
        # Only an emergency or a crisis asks the client to pick an option.
        CheckConstraint(
            "level <> 'urgent' OR client_choice IS NULL", name="ck_escalations_choice_level"
        ),
        CheckConstraint(
            "(client_choice IS NULL) = (chosen_at IS NULL)", name="ck_escalations_choice_pair"
        ),
        CheckConstraint("status IN ('not_reviewed', 'reviewed')", name="ck_escalations_status"),
        CheckConstraint(
            "(status = 'reviewed') = (reviewed_at IS NOT NULL AND reviewed_by_id IS NOT NULL)",
            name="ck_escalations_review_pair",
        ),
        # The open holds of a conversation, read with every message and reply.
        Index(
            "ix_escalations_open_holds",
            "conversation_id",
            postgresql_where=text("level IN ('emergency', 'crisis') AND client_choice IS NULL"),
        ),
        # The review list: not yet reviewed first, newest first.
        Index("ix_escalations_status_detected", "status", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # The profile it's about: the client's own, or a family member's (story 3.2's "linked to
    # the family member's profile"). The type is kept here for when the profile is gone.
    profile_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # self | family_member | teen (a teen with their own account, talking for themself)
    profile_type: Mapped[str]
    conversation_id: Mapped[uuid.UUID]
    # The client message that was checked; one escalation per message.
    message_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    # The Oracle line with the story's advice, which the backend saved straight away.
    response_message_id: Mapped[uuid.UUID]
    level: Mapped[str]  # urgent | emergency | crisis
    # What the advice gave: the local emergency number instead of 911 and 988, and Poison
    # Control's number (US only).
    outside_us: Mapped[bool]
    poison_control: Mapped[bool]
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Emergency and crisis only: what the client picked, and when. Null is "No response".
    client_choice: Mapped[str | None]  # called_for_help | reached_out | safe_now
    chosen_at: Mapped[datetime | None]
    # The support team's review (Super Admin story 4.1).
    status: Mapped[str] = mapped_column(default="not_reviewed", server_default="not_reviewed")
    reviewed_by_id: Mapped[uuid.UUID | None]
    reviewed_at: Mapped[datetime | None]


class HealthConsent(Base):
    """The Health Consent accepted for one profile (story 3.1): by the client for themself, or
    as a family member's medical advocate. A new version has to be accepted again (13.2)."""

    __tablename__ = "health_consents"
    # One acceptance per profile, version and account holder: if a profile moves to another
    # account (story 12.4), its new holder accepts again.
    __table_args__ = (UniqueConstraint("profile_id", "policy_version_id", "accepted_by_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_versions.id"))
    accepted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    accepted_at: Mapped[datetime] = mapped_column(server_default=func.now())
