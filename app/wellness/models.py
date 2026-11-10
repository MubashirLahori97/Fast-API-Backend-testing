"""The Wellness Plan (story 7.1): one per profile, created and kept up to date by the system.

- `WellnessPlan` is the plan as it is now: the clinical summary, the immediate dietary action,
  the Five Pillars' adjustments, products and notices (`content`), and its version number.
- `WellnessPlanItem` rows are its focus areas and To Do items, so ticking one changes one row
  and keeps its id across updates. Removed items stay, marked removed, for the history.
- `WellnessPlanVersion` records every update: a snapshot of the whole plan afterwards and the
  ids of what changed (7.1: "Every plan update is recorded in the backend with the date and
  what changed, for audit. Only the latest version is shown to the Client.").

Reached only through an account that owns the profile, so a teen with their own account's plan
is never seen from the parent's account. Everything but ids, codes, numbers and times is health
data: stored in plain text until Phase 4 adds field encryption, never logged, never in audit
events, job payloads or notification text.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

TRIGGERS = "('guidance_summary', 'visit_logged', 'visit_edited', 'visit_deleted', 'health_profile')"


class WellnessPlan(Base):
    """The row is made when the first update starts (version 0, no content), so two updates
    can't both create a plan; the plan exists for the apps once version 1 is saved."""

    __tablename__ = "wellness_plans"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_wellness_plans_version"),
        CheckConstraint(
            "(version = 0) = (content IS NULL) AND (version = 0) = (content_updated_at IS NULL)",
            name="ck_wellness_plans_content",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True
    )
    version: Mapped[int] = mapped_column(default=0)  # the latest version's number
    # {"clinical_summary", "immediate_dietary_action", "pillars": {code: {...}}, "products",
    #  "notices", "conflicts"}: the shape app/wellness/updates.py writes.
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_updated_at: Mapped[datetime | None]  # "Last updated"
    # The last update failed and the worker will try again (7.1's "I couldn’t update your
    # Wellness Plan just now. I’ll try again shortly."). Cleared by the next success.
    update_failed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WellnessPlanItem(Base):
    """A focus area or a To Do item."""

    __tablename__ = "wellness_plan_items"
    __table_args__ = (
        Index("ix_wellness_plan_items_plan_kind", "plan_id", "kind"),
        Index("ix_wellness_plan_items_source", "source_id"),
        CheckConstraint("kind IN ('focus_area', 'todo')", name="ck_wellness_plan_items_kind"),
        CheckConstraint("status IN ('open', 'done')", name="ck_wellness_plan_items_status"),
        # Only To Do items have a tick box.
        CheckConstraint("kind = 'todo' OR status = 'open'", name="ck_wellness_plan_items_tick"),
        CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL) "
            "AND (status = 'done') = (completed_by IS NOT NULL)",
            name="ck_wellness_plan_items_completed",
        ),
        CheckConstraint(
            "completed_by IN ('client', 'oracle')", name="ck_wellness_plan_items_completed_by"
        ),
        CheckConstraint(
            "(removed_at IS NULL) = (removed_reason IS NULL)",
            name="ck_wellness_plan_items_removed",
        ),
        CheckConstraint(
            "removed_reason IN ('resolved', 'course_finished', 'removed', 'visit_deleted')",
            name="ck_wellness_plan_items_removed_reason",
        ),
        CheckConstraint(
            "source_type IN ('guidance_summary', 'visit_log', 'health_profile')",
            name="ck_wellness_plan_items_source_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wellness_plans.id", ondelete="CASCADE"))
    kind: Mapped[str]  # focus_area | todo
    title: Mapped[str]  # the focus area's title, or the To Do item's text
    # Focus areas: {"recommendations", "time_frame"}. To Do items: {"protocol", "product"}.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Order within the plan: focus areas show the highest first (newest at the top), To Do
    # items the lowest first.
    position: Mapped[int]
    status: Mapped[str] = mapped_column(default="open")  # open | done
    completed_at: Mapped[datetime | None]
    completed_by: Mapped[str | None]  # client (ticked) | oracle (a visit or check-in said so)
    # The day its time frame ends or it's due: its check-in is sent then.
    follow_up_on: Mapped[date | None]
    # What added it: a guidance summary, a visit log or a health profile change. A plain id, so
    # a deleted visit log's items can stay (5.2: the client chooses).
    source_type: Mapped[str]
    source_id: Mapped[uuid.UUID | None]
    # resolved | course_finished (focus areas, 7.1) | removed (by an update) | visit_deleted
    removed_at: Mapped[datetime | None]
    removed_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WellnessPlanVersion(Base):
    """One update of the plan, kept for the audit (7.1). Never shown to the client."""

    __tablename__ = "wellness_plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version"),
        CheckConstraint(f"trigger IN {TRIGGERS}", name="ck_wellness_plan_versions_trigger"),
        CheckConstraint(
            "outcome IN ('created', 'updated', 'resolved')",
            name="ck_wellness_plan_versions_outcome",
        ),
        CheckConstraint("version >= 1", name="ck_wellness_plan_versions_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wellness_plans.id", ondelete="CASCADE"))
    version: Mapped[int]
    # guidance_summary | visit_logged | visit_edited | visit_deleted | health_profile
    trigger: Mapped[str]
    source_id: Mapped[uuid.UUID | None]  # the summary or visit log; none for a profile change
    # created | updated | resolved (a focus area came off because the concern resolved): which
    # of 7.1's messages the plan shows.
    outcome: Mapped[str]
    # The whole plan after this update: content plus every item that isn't removed.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # What changed, by id: {"added", "updated", "completed", "removed": [item ids], "fields":
    # [content keys]}.
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
