import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HealthProfile(Base):
    """One row per profile once its health profile exists: when it last changed (story 6.1's
    review reminders, and 4.1's "Update your health profile" widget). Created when the intake
    is completed, and touched by every change in My Health or from a conversation."""

    __tablename__ = "health_profiles"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    updated_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class HealthAnswer(Base):
    """A saved answer to one question in the bank (app/health/questions.json).

    `answer` is health data: {"value": ..., "other": "..."}, where "other" is the write-in.
    Stored in plain text until the Phase 4 field encryption is added, never logged, and never
    in audit events or job payloads. Answers to questions that no longer apply are kept, but
    aren't shown, counted or given to the Oracle (app/health/routing.py)."""

    __tablename__ = "health_answers"
    __table_args__ = (
        UniqueConstraint("profile_id", "question_key"),
        CheckConstraint("source IN ('client', 'conversation')", name="ck_health_answers_source"),
        # Story 6.1: an answer from a conversation shows where it came from. The conversation
        # may be purged later (SET NULL), so only answers from one can name one.
        CheckConstraint(
            "source = 'conversation' OR conversation_id IS NULL",
            name="ck_health_answers_conversation_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    question_key: Mapped[str]
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str]  # client | conversation
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class HealthFact(Base):
    """A change to the health profile a logged visit suggests, waiting for the client to say
    whether to save it (story 5.2: the Oracle asks before updating the health profile).
    Confirming writes it as an answer; discarding clears the value. Details from conversations
    aren't facts since the 6 Nov 19:22 stories: they're saved straight to `health_answers`.
    Rows with a conversation_id are from before that change.

    At most one pending fact per question and profile: a newer one replaces it."""

    __tablename__ = "health_facts"
    __table_args__ = (
        Index(
            "uq_health_facts_one_pending_per_question",
            "profile_id",
            "question_key",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'discarded')", name="ck_health_facts_status"
        ),
        CheckConstraint(
            "(status = 'pending') = (resolved_at IS NULL)", name="ck_health_facts_resolved"
        ),
        # A discarded fact keeps no value: the client said it was wrong or not to keep it.
        CheckConstraint("(status = 'discarded') = (answer IS NULL)", name="ck_health_facts_answer"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    question_key: Mapped[str]
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # as HealthAnswer.answer
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(default="pending")  # pending | confirmed | discarded
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None]
