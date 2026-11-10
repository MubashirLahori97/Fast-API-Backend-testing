"""Family members when the Family plan ends and starts again (story 11.3).

The Family plan ends when the client cancels (at the end of the period), downgrades to
Individual (at the next billing date), or a failed payment isn't fixed by the end of the grace
period. Then:

- managed family members are turned off with the same logic as 8.2's Turn off
  (profiles.service.turn_off_family_member): their information is kept, they're hidden from
  the profile panel and can't be used, their reminders pause (notifications skip turned-off
  profiles), and the app falls back to the default profile. Each is remembered in
  paused_family_members, and the client is told;
- invited teens' access is paused (pause_invited_teens; the gate is app/teens/access.py), and
  restored when the plan is active again. They keep their places throughout.

When the Family plan is active again, the members turned off that way are turned back on, if
they all fit in the plan's places. If they don't, they all stay off, and the client chooses who
to turn back on in Manage Family, or adds add-ons (8.2). GET /billing/subscription then shows
"Your plan includes 3 family members. Choose who to turn back on, or add another member."

It runs in a job (SYNC_JOB), queued in the same transaction as the plan change, so it happens
within seconds and is retried if it fails. It looks at the plan as it is when it runs, so running
it twice, or late, does the right thing.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.billing.models import PausedFamilyMember
from app.core import audit, jobs
from app.core.errors import AppError
from app.notifications import service as notifications
from app.profiles import service as profiles
from app.profiles.models import Profile

SYNC_JOB = "billing.sync_family_members"  # see app/billing/jobs.py

# 8.2's refusals that mean "leave this member as they are", rather than "try again later".
_SKIP = frozenset({"last_active_profile", "deletion_requested", "intake_incomplete"})


def queue_sync(db: Session, account: User) -> None:
    """Call in the transaction that changes the plan. Caller commits."""
    jobs.enqueue(db, SYNC_JOB, {"account_id": str(account.id)})


def sync(db: Session, account_id: uuid.UUID) -> None:
    """Brings the account's family members in line with its plan (SYNC_JOB). Each member is
    turned off or on in its own transaction, as 8.2 does it."""
    account = db.get(User, account_id)
    if account is None:
        return  # deleted since
    if entitlements.plan(account) == "family":
        _restore(db, account)
    else:
        _pause(db, account)
    db.commit()


def waiting(db: Session, account: User) -> list[Profile]:
    """Members the Family plan's end turned off, still off from that turn-off, and not being
    deleted: the ones to turn back on."""
    rows = db.execute(
        select(PausedFamilyMember, Profile)
        .join(Profile, Profile.id == PausedFamilyMember.profile_id)
        .where(PausedFamilyMember.account_id == account.id)
        .order_by(Profile.created_at)
    ).all()
    return [
        profile
        for row, profile in rows
        if profile.turned_off_at == row.turned_off_at and profile.deletion_requested_at is None
    ]


def _pause(db: Session, account: User) -> None:
    members = db.scalars(
        select(Profile)
        .where(
            Profile.account_id == account.id,
            Profile.is_self.is_(False),
            Profile.intake_completed_at.is_not(None),
            Profile.turned_off_at.is_(None),
            Profile.deletion_requested_at.is_(None),
        )
        .order_by(Profile.created_at)
    ).all()
    paused = 0
    for member in members:
        started = datetime.now(UTC)
        try:
            # Commits. request=None: the system does it, not the client (the audit event below
            # says why).
            profiles.turn_off_family_member(db, member, account, None)
        except AppError as error:
            db.rollback()
            # An advocate-only client's last active member stays on (8.2's rule). Without a
            # plan nothing can be used anyway, and the Individual plan is refused to them.
            if error.code in _SKIP:
                continue
            raise
        if member.turned_off_at is None or member.turned_off_at < started:
            continue  # the client turned them off just before: theirs to turn back on
        db.execute(
            insert(PausedFamilyMember)
            .values(
                id=uuid.uuid4(),
                account_id=account.id,
                profile_id=member.id,
                turned_off_at=member.turned_off_at,
            )
            .on_conflict_do_update(
                index_elements=[PausedFamilyMember.profile_id],
                set_={"turned_off_at": member.turned_off_at},
            )
        )
        audit.record(
            db,
            "billing.family_member_paused",
            target_type="profile",
            target_id=member.id,
            details={"account_id": str(account.id)},
        )
        db.commit()
        paused += 1
    if paused:
        notifications.notify(db, account, "family_members_turned_off")
    pause_invited_teens(db, account)


def _restore(db: Session, account: User) -> None:
    candidates = waiting(db, account)
    # Rows for members turned on (or off again) by the client since are finished with.
    db.execute(
        delete(PausedFamilyMember).where(
            PausedFamilyMember.account_id == account.id,
            PausedFamilyMember.profile_id.not_in([profile.id for profile in candidates]),
        )
    )
    free = entitlements.family_members_included(account) - entitlements.family_members_used(
        db, account
    )
    restored = 0
    if candidates and len(candidates) <= free:
        for profile in candidates:
            try:
                profiles.turn_on_family_member(db, profile, account, None)  # commits
            except AppError as error:
                db.rollback()
                if error.code in _SKIP or error.code.startswith("family_"):
                    continue  # the client turned another on meanwhile: they choose the rest
                raise
            db.execute(
                delete(PausedFamilyMember).where(PausedFamilyMember.profile_id == profile.id)
            )
            audit.record(
                db,
                "billing.family_member_restored",
                target_type="profile",
                target_id=profile.id,
                details={"account_id": str(account.id)},
            )
            db.commit()
            restored += 1
    if restored:
        notifications.notify(db, account, "family_members_turned_on")
    restore_invited_teens(db, account)


def pause_invited_teens(db: Session, account: User) -> int:
    """Each joined teen's access is paused, keeping their information (11.3); a paused teen can
    still sign in and use Privacy & Data only (1.5). The access gate already follows the plan;
    this tells the parent ("teen_access_paused") and the teen ("access_paused"), once per plan
    end. Returns how many were paused. The caller commits (app/teens/service.py)."""
    from app.teens import service as teens  # app.teens imports this package

    return teens.pause_for_plan_end(db, account)


def restore_invited_teens(db: Session, account: User) -> int:
    """Invited teens' access is back when the Family plan is active again (11.3), and the parent
    is told ("teen_access_restored"). Teens keep their places while the plan has ended, so
    there's nothing to fit in. Returns how many were restored. The caller commits."""
    from app.teens import service as teens  # app.teens imports this package

    return teens.restore_for_plan(db, account)
