"""What the client's plan allows (stories 8.1, 8.2, 9.1 and 11.3).

The account's row in `subscriptions` (app/billing/models.py) is the source of truth. A
subscription gives access while it's active, while a failed payment is in its grace period
(past_due), and after a cancellation until the end of the period paid for. Those times are
checked here, so access ends on time even before the worker has marked the subscription
ended. Without a subscription that gives access, the client is on the free trial, which ends at
`users.trial_ends_at` (14 days after verification, story 1.1); an ended subscription goes back
to that locked state (11.3).

The plans: "individual" (the client's own profile only) and "family" (the client plus
`catalog.family_members_included()` family members, plus any paid add-ons). The trial includes no
family members, and greys out everything but conversations (feature_access).

`users.subscription_plan` is a copy kept in step by app/billing/service.py, for SQL filters such
as the trial reminders. Read the plan through these functions instead.
"""

from datetime import UTC, datetime
from typing import Literal, get_args

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app.auth.models import User
from app.billing import catalog
from app.billing.models import Subscription
from app.core.errors import AppError
from app.profiles.models import Profile
from app.teens.models import TeenLink

Plan = Literal["trial", "individual", "family"]
PAID_PLANS = ("individual", "family")

# What the trial greys out (story 9.1), and what the Individual plan doesn't include.
Feature = Literal[
    "conversations",  # the message box: locked once the trial or subscription has ended
    "my_health",  # 6.1
    "visit_notes",  # My Visit Notes and visit logging, 5.1 and 5.2
    "wellness_plan",  # 7.1
    "family_members",  # adding or turning on family members, 8.1 and 8.2 (Family plan only)
    "teen_invites",  # inviting a teen to their own account, 1.5 (Family plan only)
    "downloads",  # downloading, printing or copying summaries and provider notes, 3.3 and 3.5
]
FEATURES: tuple[Feature, ...] = get_args(Feature)
FAMILY_ONLY: frozenset[Feature] = frozenset({"family_members", "teen_invites"})

TRIAL_ENDED = "Your free trial has ended. Choose a plan to keep talking with me."
# Not in the stories (docs/decisions/phase-8-billing.md): 11.3 says an ended subscription goes
# back to the locked state "as when a trial ends", but the trial text would be wrong here.
SUBSCRIPTION_ENDED = "Your subscription has ended. Choose a plan to keep talking with me."
# Story 9.1: a greyed-out feature tapped during the trial.
UPGRADE_TO_UNLOCK = "This is part of your plan. Choose a plan to unlock it."
# Stories 2.2 and 4.2. Story 8.1 words it differently (docs/decisions/r2-profiles.md).
FAMILY_LIMIT_REACHED = (
    "You’ve added all the family members included in your plan. Add another member to continue."
)
# Story 8.1's "Teens can't add" (not in the stories' messages; docs/decisions/phase-3b-teens.md).
TEEN_ACCOUNT_NO_FAMILY = "Adding family members isn’t available on a teen account."


def _teen(user: User) -> bool:
    """A teen with their own account (story 1.5): no trial and no plan of their own. Their access
    follows the parent's Family plan, which the policy gate checks (app/teens/access.py)."""
    return user.account_type == "teen"


def subscription(user: User) -> Subscription | None:
    """The account's subscription row, whatever its status. Read in the session the account
    was loaded in, so these functions keep their one-argument form."""
    db = object_session(user)
    if db is None:
        raise RuntimeError("The account must be loaded in a database session.")
    return db.scalar(select(Subscription).where(Subscription.account_id == user.id))


def access_until(sub: Subscription) -> datetime | None:
    """When the subscription's access ends; None while it renews."""
    if sub.status == "active":
        return None
    if sub.status == "past_due":
        return sub.grace_ends_at
    if sub.status == "cancelled":
        # Cancelled while a payment had failed: the grace period still runs.
        return max(sub.current_period_end, sub.grace_ends_at or sub.current_period_end)
    return sub.ended_at


def gives_access(sub: Subscription | None, now: datetime | None = None) -> bool:
    if sub is None or sub.status == "ended":
        return False
    until = access_until(sub)
    return until is None or until > (now or datetime.now(UTC))


def _paid(user: User) -> Subscription | None:
    """The subscription, if it gives access now."""
    sub = subscription(user)
    return sub if gives_access(sub) else None


def plan(user: User) -> Plan:
    """The plan the client can use now. "trial" also covers an ended subscription; then
    trial_ended() is true and the message box is locked."""
    sub = _paid(user)
    return sub.plan if sub is not None else "trial"


def trial_ended(user: User) -> bool:
    """The message box is locked: the free trial is over and no subscription gives access
    (story 9.1). An ended subscription counts too (11.3); the name is from before Phase 8.
    Never for a teen with their own account: they have no trial (1.5)."""
    if _teen(user):
        return False
    return plan(user) == "trial" and user.trial_ends_at <= datetime.now(UTC)


def trial_days_left(user: User) -> int | None:
    """Story 9.1's "days left", rounded up; None once the trial is over or they've subscribed."""
    if _teen(user) or plan(user) != "trial":
        return None
    left = (user.trial_ends_at - datetime.now(UTC)).total_seconds()
    return max(1, -(-int(left) // 86400)) if left > 0 else None


def check_can_talk(user: User) -> None:
    """Story 3.1: once the trial or the subscription ends, the message box is locked. Past
    conversations can still be read (open question 11)."""
    if trial_ended(user):
        if subscription(user) is not None:
            raise AppError(403, "subscription_ended", SUBSCRIPTION_ENDED)
        raise AppError(403, "trial_ended", TRIAL_ENDED)


def feature_access(user: User) -> dict[Feature, bool]:
    """Which features are locked (True): greyed out, with the upgrade prompt when tapped.

    - The trial: conversations for the client's own profile, guidance summaries and provider
      notes viewed in the conversation (9.1). Everything else is locked, and conversations
      too once it has ended.
    - Individual: everything but family members and teen invites.
    - Family: everything.
    - A teen with their own account: everything but family members and teen invites (1.5,
      8.1). Their access follows the parent's Family plan, and while it's paused the policy
      gate refuses every feature anyway (app/teens/access.py)."""
    if _teen(user):
        return {feature: feature in FAMILY_ONLY for feature in FEATURES}
    current = plan(user)
    if current == "trial":
        return {feature: feature != "conversations" or trial_ended(user) for feature in FEATURES}
    return {feature: current == "individual" and feature in FAMILY_ONLY for feature in FEATURES}


def check_feature(user: User, feature: Feature) -> None:
    """For the endpoints behind a locked feature: refuses with the story's upgrade prompt."""
    if not feature_access(user)[feature]:
        return
    if feature == "conversations":
        check_can_talk(user)
    if feature in FAMILY_ONLY and _teen(user):
        raise AppError(403, "teen_account", TEEN_ACCOUNT_NO_FAMILY)
    if feature in FAMILY_ONLY:
        raise AppError(
            403,
            "family_plan_required",
            "Adding family members is part of the Family plan. Upgrade to add someone.",
        )
    raise AppError(403, "upgrade_required", UPGRADE_TO_UNLOCK)


def family_members_included(user: User) -> int:
    """Places for family members: only the Family plan has any (stories 8.1 and 9.1), plus
    its paid add-ons."""
    sub = _paid(user)
    if sub is None or sub.plan != "family":
        return 0
    return catalog.family_members_included() + sub.add_on_members


def family_members_used(db: Session, user: User) -> int:
    """Active family members (story 8.1). A draft doesn't take a place until its intake is
    done, and a turned-off member gives theirs up (story 8.2). A member whose deletion was
    requested keeps their place until the deletion is done, unless they were turned off.

    Invited teens with their own account count too, from the moment of the invite (8.1),
    until they're turned off or removed, or move to an adult account (1.6)."""
    managed = db.scalar(
        select(func.count())
        .select_from(Profile)
        .where(
            Profile.account_id == user.id,
            Profile.is_self.is_(False),
            Profile.intake_completed_at.is_not(None),
            Profile.turned_off_at.is_(None),
        )
    )
    teens = db.scalar(
        select(func.count())
        .select_from(TeenLink)
        .where(TeenLink.parent_account_id == user.id, TeenLink.turned_off_at.is_(None))
    )
    return managed + teens


def check_can_add_family_member(db: Session, user: User, name: str | None = None) -> None:
    """Refuses when the plan has no room for another member. Before the member's name is known,
    the upgrade message says "someone" (stories 4.2 and 9.1); after, it names them (2.2, 8.1).
    When the Family plan is full, the app offers an add-on (POST /billing/subscription/add-ons)
    and then tries again. A teen with their own account can't add anyone (8.1)."""
    if _teen(user):
        raise AppError(403, "teen_account", TEEN_ACCOUNT_NO_FAMILY)
    if plan(user) != "family":
        raise AppError(
            403,
            "family_plan_required",
            "Adding family members is part of the Family plan. "
            f"Upgrade to add {name or 'someone'}.",
        )
    if family_members_used(db, user) >= family_members_included(user):
        raise AppError(403, "family_limit_reached", FAMILY_LIMIT_REACHED)


def check_can_turn_on_family_member(db: Session, user: User, name: str) -> None:
    """Story 8.2: turning a member back on needs a free place, the same as adding one. The
    caller holds the account row lock, so two members can't take the last place at once."""
    if _teen(user):
        raise AppError(403, "teen_account", TEEN_ACCOUNT_NO_FAMILY)
    if plan(user) != "family":
        raise AppError(
            403,
            "family_plan_required",
            f"Family members are part of the Family plan. Upgrade to turn on {name}’s profile.",
        )
    included = family_members_included(user)
    if family_members_used(db, user) >= included:
        members = "family member" if included == 1 else "family members"
        raise AppError(
            403,
            "family_limit_reached",
            f"You have {included} active {members}, the most your plan includes. "
            "Add another member, or turn off another family member first.",
        )
