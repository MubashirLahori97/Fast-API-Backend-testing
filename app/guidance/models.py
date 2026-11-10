"""Guidance summaries (story 3.3) and provider-ready notes (stories 3.4 and 3.5).

Both are written by the Oracle from one conversation and belong to that conversation's
profile, so they're reached only through an account that owns the profile: a teen with their
own account owns their profile, and the parent's account never sees it.

Everything here except the ids, codes and times is health data: stored in plain text until
Phase 4 adds field encryption (docs/PLAN.md), never logged, never in audit events, job payloads,
URLs or notification text. The `content` columns hold what the Oracle returned, cleaned, in the
shape of the dataclasses in app/oracle/contract.py.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GuidanceSummary(Base):
    """The conversation's guidance summary (story 3.3). There's one per conversation, updated
    when the client shares more rather than repeated (Session 10).

    The row is made when the first summary is asked for, so two requests can't both make one;
    until the Oracle's first summary is saved, `content` is null and the summary doesn't exist
    as far as the apps can tell."""

    __tablename__ = "guidance_summaries"
    __table_args__ = (
        CheckConstraint("stage IN ('first_look', 'full')", name="ck_guidance_summaries_stage"),
        # The content, its stage and its times are set together, by the first summary saved.
        CheckConstraint(
            "(content IS NULL) = (stage IS NULL) AND (content IS NULL) = (shared_at IS NULL) "
            "AND (content IS NULL) = (content_updated_at IS NULL)",
            name="ck_guidance_summaries_content",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    # first_look: what the Oracle could say so far, when the client asked early | full
    stage: Mapped[str | None]
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The latest client message the summary was written from. A refresh with no client message
    # since then returns the summary unchanged, without asking the Oracle.
    covers_message_id: Mapped[uuid.UUID | None]
    shared_at: Mapped[datetime | None]  # when the first summary was shared
    content_updated_at: Mapped[datetime | None]  # when it was last written or updated
    # When a request started asking the Oracle for it: one at a time. A claim older than
    # settings.guidance_claim_seconds belongs to a request that died.
    generation_started_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProviderNote(Base):
    """One set of provider-ready notes (story 3.4), for one appointment. A conversation can
    have several, one per appointment (question 15, docs/decisions/phase-5-guidance-and-notes.md).

    The appointment details here are the current ones: the client can edit them at any time
    (3.5). The content is read-only for the client and lives in versions: a new version is
    written when the specialty changes or the client asks the Oracle for a change, and the
    earlier ones, the original included, are kept."""

    __tablename__ = "provider_notes"
    __table_args__ = (
        # A create sent again after a lost connection finds the notes it already made.
        UniqueConstraint("conversation_id", "client_request_id"),
        Index("ix_provider_notes_profile_created", "profile_id", "created_at"),
        # A write-in exactly when the specialty is "other".
        CheckConstraint(
            "(specialty = 'other') = (specialty_other IS NOT NULL)",
            name="ck_provider_notes_specialty_other",
        ),
        CheckConstraint("version >= 1", name="ck_provider_notes_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    client_request_id: Mapped[uuid.UUID]  # made by the app once per create
    # A code from settings.provider_specialties, or "other" with the client's write-in.
    specialty: Mapped[str]
    specialty_other: Mapped[str | None]
    provider_name: Mapped[str | None]
    appointment_date: Mapped[date | None]
    version: Mapped[int] = mapped_column(default=1)  # the current version's number
    # As on GuidanceSummary: one Oracle request at a time per set of notes.
    generation_started_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProviderNoteVersion(Base):
    """One version of a set of notes' content. Version 1 is the original."""

    __tablename__ = "provider_note_versions"
    __table_args__ = (
        UniqueConstraint("note_id", "version"),
        CheckConstraint(
            "reason IN ('created', 'specialty_changed', 'updated_from_conversation')",
            name="ck_provider_note_versions_reason",
        ),
        CheckConstraint(
            "(specialty = 'other') = (specialty_other IS NOT NULL)",
            name="ck_provider_note_versions_specialty_other",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_notes.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    reason: Mapped[str]  # created | specialty_changed | updated_from_conversation
    # The specialty it was written for.
    specialty: Mapped[str]
    specialty_other: Mapped[str | None]
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The latest client message it was written from (see GuidanceSummary.covers_message_id).
    covers_message_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
