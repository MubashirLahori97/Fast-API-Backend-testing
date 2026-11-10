"""Story 7.1's automatic updates: what other packages call when something new is saved for a
profile. Each one queues a `wellness.update_plan` job, which asks the Oracle with only the new
item and saves the new version (app/wellness/updates.py). Nothing here commits: the job is
saved with the caller's own changes, so it only runs if they were saved.

This module imports no service module, so app/guidance and app/health can import it.
Job payloads hold ids only.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.core import jobs
from app.core.jobs import Job
from app.profiles.models import Profile
from app.wellness.models import WellnessPlan

UPDATE_JOB = "wellness.update_plan"  # see app/wellness/jobs.py


def plan_allowed(account: User) -> bool:
    """7.1: "No plan is created or updated for free trial Clients" (nor after a subscription
    ended)."""
    return not entitlements.feature_access(account)["wellness_plan"]


def plan_exists(db: Session, profile: Profile) -> bool:
    version = db.scalar(select(WellnessPlan.version).where(WellnessPlan.profile_id == profile.id))
    return bool(version)


def _queue(
    db: Session,
    profile: Profile,
    trigger: str,
    source_id: uuid.UUID | None = None,
    revision: int | None = None,
) -> None:
    payload: dict[str, str | int] = {"profile_id": str(profile.id), "trigger": trigger}
    if source_id is not None:
        payload["source_id"] = str(source_id)
    if revision is not None:
        payload["revision"] = revision
    # The same update already waiting (several saves in a row): one run covers them.
    waiting = db.scalar(
        select(Job.id)
        .where(Job.kind == UPDATE_JOB, Job.status == "pending", Job.payload.contains(payload))
        .limit(1)
    )
    if waiting is None:
        jobs.enqueue(db, UPDATE_JOB, payload)


def summary_shared(db: Session, account: User, profile: Profile, summary_id: uuid.UUID) -> None:
    """A full guidance summary was saved (3.3): the plan is created from the profile's first
    one, and updated with each later one."""
    if plan_allowed(account):
        _queue(db, profile, "guidance_summary", summary_id)


def visit_saved(
    db: Session,
    account: User,
    profile: Profile,
    visit_log_id: uuid.UUID,
    revision: int,
    *,
    edited: bool,
) -> None:
    """A provider visit was logged or edited (5.2): its next steps and tests join the To Do
    list. Only once the profile has a plan."""
    if plan_allowed(account) and plan_exists(db, profile):
        trigger = "visit_edited" if edited else "visit_logged"
        _queue(db, profile, trigger, visit_log_id, revision)


def health_profile_changed(db: Session, account: User, profile: Profile) -> None:
    """The health profile changed (6.1): new medicines are checked against the plan, and new
    measurements update the Diet pillar. Only once the profile has a plan."""
    if plan_allowed(account) and plan_exists(db, profile):
        _queue(db, profile, "health_profile")
