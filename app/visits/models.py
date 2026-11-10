"""Logged provider visits (story 5.2).

A visit log belongs to one profile, and is reached only through an account that owns it: a
teen with their own account owns their profile, so the parent never sees their logs. It may be
for a set of provider-ready notes (`provider_note_id`), one log per set, or standalone.

Everything here except the ids, codes and times is health data: stored in plain text until
Phase 4 adds field encryption (docs/PLAN.md), never logged, never in audit events, job payloads,
URLs or notification text. Deleting a log deletes the row; the audit event that records it
holds ids only.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

GENESIS_STATUSES = "('taking', 'started', 'stopped', 'not_taking')"


class VisitLog(Base):
    __tablename__ = "visit_logs"
    __table_args__ = (
        # A save sent again after a lost connection finds the log it already made.
        UniqueConstraint("profile_id", "client_request_id"),
        # One log per set of notes (NULLs, the standalone visits, don't collide).
        UniqueConstraint("provider_note_id"),
        Index("ix_visit_logs_profile_created", "profile_id", "created_at"),
        CheckConstraint(
            "(specialty = 'other') = (specialty_other IS NOT NULL)",
            name="ck_visit_logs_specialty_other",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'ready', 'failed')", name="ck_visit_logs_review_status"
        ),
        CheckConstraint(
            "(review_status = 'ready') = (review IS NOT NULL)", name="ck_visit_logs_review"
        ),
        CheckConstraint(
            f"genesis_gold_status IN {GENESIS_STATUSES}", name="ck_visit_logs_genesis_gold"
        ),
        CheckConstraint(
            f"sacred_seven_status IN {GENESIS_STATUSES}", name="ck_visit_logs_sacred_seven"
        ),
        CheckConstraint("revision >= 1", name="ck_visit_logs_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    # The provider-ready notes this visit was for. Purging the notes' conversation leaves the
    # log, which is then shown as a standalone visit.
    provider_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_notes.id", ondelete="SET NULL")
    )
    client_request_id: Mapped[uuid.UUID]  # made by the app once per new log
    # Counts saves (1 when logged, +1 per edit), so a review or plan update queued for an older
    # save knows it's out of date.
    revision: Mapped[int] = mapped_column(default=1)

    # Story 5.2's Provider Visit Summary.
    visit_date: Mapped[date]
    reason: Mapped[str]  # why you went: what they wanted help with
    duration: Mapped[str | None]  # how long it's been going on
    # A code from settings.provider_specialties, or "other" with the client's write-in.
    specialty: Mapped[str]
    specialty_other: Mapped[str | None]
    provider_name: Mapped[str | None]
    practice: Mapped[str | None]  # practice or clinic
    follow_up_date: Mapped[date | None]  # the follow-up appointment
    # What I took away.
    diagnosis: Mapped[str | None]
    understanding: Mapped[str | None]
    unaddressed_concerns: Mapped[str | None]
    # [{"name", "ordered", "ordered_by", "status", "from_notes"}]; status is
    # pending | drawn | resulted, or null for a lab that wasn't ordered.
    labs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{"name", "change", "new_dose"}]; change is new | dose_increased | dose_decreased |
    # discontinued | continued | added.
    medicine_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Adults only: taking | started | stopped | not_taking.
    genesis_gold_status: Mapped[str | None]
    sacred_seven_status: Mapped[str | None]
    # [{"text", "priority"}]; priority is routine | schedule | urgent.
    next_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    own_notes: Mapped[str | None]

    # The Oracle's review (5.2's "What the Oracle does with the visit"), made by the
    # visits.review job after each save: pending until it's done, failed while it's retried.
    review_status: Mapped[str] = mapped_column(default="pending")
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
