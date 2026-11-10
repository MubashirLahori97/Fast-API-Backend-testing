"""Story 1.5's access gate for teens with their own account (and 1.2, 8.2, 11.4, 12.2).

A teen can use the app only while all of these hold:

- they're linked to a parent (the link wasn't removed, and the parent's account still exists);
- the link isn't turned off (8.2);
- the parent's account is active, their Family plan gives access (1.5, 11.3), their consent
  isn't revoked and their account isn't waiting for deletion (11.4), they've accepted the
  current policies (12.2), and they've given the current Health Consent for this teen (12.2);
- the teen is under the age of majority (1.6).

One exception (8.2, 6 Nov 19:22): a teen the parent removed isn't linked any more, but keeps
full use for the removal's 10-day grace period (`in_removal_grace`). A teen whose account is
locked for deletion (their own request, a removal, or the parent's Account Deletion, after the
grace period) is refused before this gate, by accounts.service.deletion_locked.

When the gate is shut the teen can still sign in, but only Privacy & Data works (export and
delete); the policy gate (ClientSession) refuses everything else with ACCESS_PAUSED. A teen who
has reached the age of majority gets 1.6's AGE_OF_MAJORITY_REACHED instead, and the Create My
Account step.

Everything here is worked out on each request from the current rows, so access follows the
parent's plan, toggle and policies straight away (1.5, 8.2 and 12.2's non-functional
requirements). Nothing about the teen is stored to say they're paused.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import OPEN_DELETION_STATUSES, DeletionRequest, PolicyVersion
from app.auth.models import User
from app.billing import entitlements
from app.core.ages import age_on, us_today
from app.core.config import settings
from app.teens.models import TeenLink

# The gate's messages (ACCESS_PAUSED, AGE_OF_MAJORITY_REACHED) are in app/privacy/teens.py, next
# to the hooks the policy gate calls.

TeenState = Literal["open", "paused", "aged_out"]
PauseReason = Literal[
    "turned_off", "parent_inactive", "family_plan", "consent", "policies", "health_consent"
]
# Story 8.2's statuses on the parent's card.
LinkStatus = Literal["invite_sent", "joined", "turned_off", "access_paused"]


def is_teen_account(account: User) -> bool:
    """An invited teen with their own account (story 1.5)."""
    return account.account_type == "teen"


def adult_on(date_of_birth: date) -> date:
    """The day the age of majority is reached, the same way age_on counts it: someone born on
    29 February turns 18 on 1 March in a year without one (docs/PLAN.md, question 39)."""
    year = date_of_birth.year + settings.age_of_majority
    try:
        return date_of_birth.replace(year=year)
    except ValueError:
        return date(year, 3, 1)


def reached_majority(account: User) -> bool:
    """Story 1.6, on Hawaii's date and the account's state, like 11.1's age rules. The age is
    18 in every state for now (question 22); accounts.service.age_of_majority_in is where a
    per-state table would go."""
    from app.accounts import service as accounts  # accounts.service imports this package

    if account.date_of_birth is None:
        return False
    return age_on(account.date_of_birth, us_today()) >= accounts.age_of_majority_in(account.state)


def current_health_consent_id(db: Session) -> uuid.UUID | None:
    """The Health Consent version in force now (the conversations package's rule)."""
    return db.scalars(
        select(PolicyVersion.id)
        .where(
            PolicyVersion.kind == "health_consent",
            PolicyVersion.published_at <= datetime.now(UTC),
        )
        .order_by(PolicyVersion.published_at.desc())
        .limit(1)
    ).first()


def link_for_teen(db: Session, teen: User, *, lock: bool = False) -> TeenLink | None:
    """The link of the parent the teen joined, if it still exists."""
    stmt = select(TeenLink).where(TeenLink.teen_account_id == teen.id)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def in_removal_grace(db: Session, teen: User) -> bool:
    """Story 8.2: the parent removed this teen less than the grace period ago. The teen keeps
    full use of their account, and the parent's consent still covers them, until it ends."""
    return (
        db.scalar(
            select(DeletionRequest.id)
            .where(
                DeletionRequest.account_id == teen.id,
                DeletionRequest.kind == "teen_removal",
                DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
                DeletionRequest.locked_at.is_(None),
                DeletionRequest.grace_ends_at > datetime.now(UTC),
            )
            .limit(1)
        )
        is not None
    )


def parent_pause_reason(
    db: Session, link: TeenLink, parent: User | None = None
) -> PauseReason | None:
    """What on the parent's side keeps this teen out, or None when nothing does. Checked in the
    order the parent can fix them."""
    from app.accounts import service as accounts  # accounts.service imports this package

    if link.turned_off_at is not None:
        return "turned_off"
    parent = parent or db.get(User, link.parent_account_id)
    if parent is None or parent.status != "active":
        return "parent_inactive"
    if entitlements.plan(parent) != "family":
        return "family_plan"
    if accounts.consent_withdrawn(db, parent):
        return "consent"
    if accounts.pending_policies(db, parent):
        return "policies"
    if link.health_consent_version_id != current_health_consent_id(db):
        return "health_consent"
    return None


def state(db: Session, teen: User) -> TeenState:
    """ "open" for every account that isn't a teen's, so callers needn't check first."""
    if not is_teen_account(teen):
        return "open"
    if reached_majority(teen):
        return "aged_out"
    link = link_for_teen(db, teen)
    if link is None:
        return "open" if in_removal_grace(db, teen) else "paused"
    if parent_pause_reason(db, link) is not None:
        return "paused"
    return "open"


def link_status(db: Session, link: TeenLink, parent: User) -> LinkStatus:
    """Story 8.2's status on the parent's card: Invite sent, Joined, Turned off or Access
    paused. It never says anything about the teen's own activity."""
    if link.turned_off_at is not None:
        return "turned_off"
    if link.teen_account_id is None:
        return "invite_sent"
    if parent_pause_reason(db, link, parent) is not None:
        return "access_paused"
    return "joined"


def health_consent_needed(db: Session, link: TeenLink) -> bool:
    """Story 12.2: an updated Health Consent the parent hasn't confirmed for this teen yet."""
    return link.health_consent_version_id != current_health_consent_id(db)


def parent_consent_covers(db: Session, teen: User, policy_version_id: uuid.UUID) -> bool:
    """Story 3.1: "Teens with their own account don’t see it, because the parent gave consent."
    True while the teen's parent has given this Health Consent version for them, and during the
    grace period after the parent removed them (8.2: full use)."""
    link = link_for_teen(db, teen)
    if link is None:
        return in_removal_grace(db, teen)
    return link.health_consent_version_id == policy_version_id
