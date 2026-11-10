"""Story 4.1's Home Dashboard: every widget for the active profile, in the story's order, each
with whether it's shown and whether it's locked.

- **Built from the other phases' own functions,** so each rule lives in one place:
  conversations (`list_conversations`, with 3.2's safety holds), the Wellness Plan card,
  My Visit Notes, the health profile's completion, last update and pending facts, the
  notification count, the profile panel, invited teens' cards and the plan's entitlements.
- **Locks come from `entitlements.feature_access`:** the trial greys out everything but the
  conversation, the Individual plan only My Family, and an ended trial or subscription
  everything (with the upgrade prompt). A locked widget carries no records, and the locked
  features' own functions aren't called.
- **Read-only:** it writes, commits, schedules and sends nothing. Opening it doesn't count as
  a message, mark notifications read or start a job.
- **Only the active profile's information** is in it. A teen's own account is a separate
  account, so the parent's dashboard never reaches it (OwnedProfile); My Family shows only what
  the parent typed about an invited teen and the invite's status.

The response holds health data (topics, plan items, specialties) for the account that owns the
profile only. Nothing here is logged.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.billing.entitlements import Feature
from app.conversations import service as conversations
from app.core.ages import is_adult, today, us_today
from app.core.config import settings
from app.core.errors import AppError
from app.core.schemas import clean_line
from app.dashboard.schemas import (
    CompleteHealthProfileWidget,
    ConsultWidget,
    ConversationWidget,
    HomeDashboardOut,
    InvitedTeenCard,
    MyFamilyWidget,
    MyHealthWidget,
    NextStep,
    TopBar,
    TrialBanner,
    UpdateHealthProfileWidget,
    UpgradePrompt,
    VisitNotesWidget,
    WellnessPlanWidget,
    WhatsNextWidget,
    Widget,
)
from app.guidance.documents import MONTHS
from app.health import reminders as health_reminders
from app.health import service as health
from app.health.values import POSSESSIVE
from app.notifications import service as notifications
from app.notifications.kinds import KINDS
from app.profiles import service as profiles
from app.profiles.models import Profile
from app.teens import access as teen_access
from app.teens import service as teens
from app.visits import listing as visit_listing
from app.visits.models import VisitLog
from app.visits.schemas import VisitNoteCard, VisitNotesOut
from app.wellness import service as wellness
from app.wellness.schemas import PlanCardOut

# Story 4.1's messages.
LOAD_FAILED = "We couldn’t load your dashboard. Please try again."
GREETINGS = {
    "morning": "Good morning, {name}",
    "afternoon": "Good afternoon, {name}",
    "evening": "Good evening, {name}",
}
FAMILY_GREETING = "Here’s {name}’s space"
TRIAL_DAYS_LEFT = "{days} days left in your free trial."
ASK_PLACEHOLDER = "Ask me anything"
UPCOMING_APPOINTMENT = "Your {specialty} appointment is on {day}. Your notes are ready."
LOG_VISIT = "How did your visit go? Log it here."
# Not in the stories (docs/decisions/phase-11-dashboard.md).
TRIAL_LAST_DAY = "1 day left in your free trial."
FAMILY_UPCOMING_APPOINTMENT = (
    "{name}’s {specialty} appointment is on {day}. {possessive} notes are ready."
)
FAMILY_LOG_VISIT = "How did {name}’s visit go? Log it here."
PLAN_CHECK_IN = "Let’s check in on “{item}”. How is it going?"

# The widgets' titles: the story's names, with the family member's name where they say "your"
# (4.1: "Continue Azka’s conversation"). Some aren't in the stories (see the decisions file).
CONTINUE = "Continue your conversation"
FAMILY_CONTINUE = "Continue {name}’s conversation"
ASK = "Ask the Oracle"
WELLNESS_PLAN = "Wellness Plan"
FAMILY_WELLNESS_PLAN = "{name}’s Wellness Plan"
COMPLETE_PROFILE = "Complete your health profile"
FAMILY_COMPLETE_PROFILE = "Complete {name}’s health profile"
UPDATE_PROFILE = "Update your health profile"
FAMILY_UPDATE_PROFILE = "Update {name}’s health profile"
WHATS_NEXT = "What’s next"
VISIT_NOTES = "My Visit Notes"
MY_HEALTH = "My Health"
MY_FAMILY = "My Family"
CONSULT = "Consult with support team"

# The locked features, each with what tapping its widget shows.
Locks = dict[Feature, str]


def dashboard(
    db: Session, profile: Profile, account: User, time_zone: str | None = None
) -> HomeDashboardOut:
    """The active profile's dashboard. `profile` is usable (UsableProfile): a turned-off
    member or one being deleted can't be the active profile, so the app switches to the
    default one (4.2). Any database failure gets 4.1's "Dashboard couldn’t load" message, which
    the app shows with Try again."""
    try:
        return _build(db, profile, account, _local_now(time_zone))
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "load_failed", LOAD_FAILED) from None
    except AppError as error:
        # A widget's own "couldn’t load" (the plan card, My Visit Notes) fails the whole read.
        if error.status_code == 503:
            raise AppError(503, "load_failed", LOAD_FAILED) from None
        raise


def _build(db: Session, profile: Profile, account: User, now: datetime) -> HomeDashboardOut:
    locks = _locks(account)
    teen_account = teen_access.is_teen_account(account)
    name = clean_line(profiles.first_name(profile, account))
    # The locked features' own functions refuse with 403, so they're only called when open.
    notes = None if "visit_notes" in locks else visit_listing.visit_notes(db, profile, account)
    plan_card = None if "wellness_plan" in locks else wellness.get_card(db, profile, account).card
    completion = health.completion(db, profile)

    widgets: list[Widget] = [
        _conversation(db, profile, name, locks),
        _wellness_plan(profile, name, locks, plan_card),
        _complete_profile(profile, name, locks, completion),
        _update_profile(db, profile, name, locks, now),
        _whats_next(db, profile, name, locks, notes, plan_card),
        _visit_notes(locks, notes),
        _my_health(db, profile, account, locks, completion),
        _my_family(db, profile, account, teen_account, locks),
        # 10.1's consultations aren't gated by the plan; a teen's own account can't ask for one.
        ConsultWidget(shown=not teen_account, title=CONSULT, **_lock(locks, None)),
    ]
    stopped = _talk_stopped(account)
    return HomeDashboardOut(
        profile_id=profile.id,
        is_self=profile.is_self,
        teen_account=teen_account,
        education_only=teen_account or not is_adult(profile.date_of_birth),
        top_bar=TopBar(
            greeting=_greeting(profile, name, now),
            unread_notifications=notifications.unread_count(db, account),
            profile_initial=name[:1].upper(),
            profile_first_name=name,
        ),
        trial_banner=_trial_banner(account),
        upgrade_prompt=(
            UpgradePrompt(code=stopped.code, message=stopped.message) if stopped else None
        ),
        widgets=widgets,
    )


# Locks, the top bar and the trial


def _locks(account: User) -> Locks:
    """The features the plan locks, with the refusal their endpoints give: 9.1's "This is part
    of your plan...", the Family plan's prompt for family members, and the trial-ended (or
    subscription-ended) message for conversations."""
    locks: Locks = {}
    for feature, locked in entitlements.feature_access(account).items():
        if locked:
            try:
                entitlements.check_feature(account, feature)
            except AppError as error:
                locks[feature] = error.message
    return locks


def _lock(locks: Locks, feature: Feature | None) -> dict[str, Any]:
    message = locks.get(feature) if feature else None
    return {"locked": message is not None, "locked_message": message}


def _talk_stopped(account: User) -> AppError | None:
    """The message box's refusal once the trial or the subscription has ended, or None."""
    try:
        entitlements.check_can_talk(account)
    except AppError as error:
        return error
    return None


def _local_now(time_zone: str | None) -> datetime:
    """Now in the app's time zone, for the greeting. The backend doesn't know clients' time
    zones (docs/PLAN.md, question 8), so the app sends its own; without a known one, the
    configured default."""
    zone = _zone(time_zone) or _zone(settings.home_dashboard_time_zone) or UTC
    return datetime.now(zone)


def _zone(name: str | None) -> tzinfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _greeting(profile: Profile, name: str, now: datetime) -> str:
    """4.1: "Good morning, [First Name]" by the time of day, or "Here’s [Name]’s space" for a
    family member. Before the morning starts, it's still evening."""
    if not profile.is_self:
        return FAMILY_GREETING.format(name=name)
    if settings.home_dashboard_morning_hour <= now.hour < settings.home_dashboard_afternoon_hour:
        part = "morning"
    elif settings.home_dashboard_afternoon_hour <= now.hour < settings.home_dashboard_evening_hour:
        part = "afternoon"
    else:
        part = "evening"
    return GREETINGS[part].format(name=name)


def _trial_banner(account: User) -> TrialBanner | None:
    """The days left in the free trial. None after subscribing, once the trial is over, and on
    a teen's own account (no trial: their access comes through the parent's Family plan)."""
    days = entitlements.trial_days_left(account)
    if days is None:
        return None
    message = TRIAL_LAST_DAY if days == 1 else TRIAL_DAYS_LEFT.format(days=days)
    return TrialBanner(days_left=days, message=message)


def _titled(profile: Profile, name: str, own: str, family: str) -> str:
    return own if profile.is_self else family.format(name=name)


# The widgets, in the story's order


def _conversation(db: Session, profile: Profile, name: str, locks: Locks) -> ConversationWidget:
    """The last conversation (most recent first, deleted ones left out), or Ask the Oracle.
    After the trial or subscription ends it's locked, but past conversations can still be read
    (question 11), so the last one is still given."""
    latest = next(iter(conversations.list_conversations(db, profile, limit=1)), None)
    if latest is None:
        return ConversationWidget(
            shown=True,
            title=ASK,
            **_lock(locks, "conversations"),
            mode="ask",
            conversation_id=None,
            topic=None,
            last_message_at=None,
            safety_hold=False,
            placeholder=ASK_PLACEHOLDER,
        )
    return ConversationWidget(
        shown=True,
        title=_titled(profile, name, CONTINUE, FAMILY_CONTINUE),
        **_lock(locks, "conversations"),
        mode="continue",
        conversation_id=latest.id,
        topic=latest.topic,
        last_message_at=latest.last_message_at,
        safety_hold=latest.safety_hold,
        placeholder=None,
    )


def _wellness_plan(
    profile: Profile, name: str, locks: Locks, card: PlanCardOut | None
) -> WellnessPlanWidget:
    """Shown once the profile has a plan. During the trial (and after a subscription ends) it's
    shown greyed out, as 7.1 says, without the plan."""
    locked = "wellness_plan" in locks
    return WellnessPlanWidget(
        shown=locked or card is not None,
        title=_titled(profile, name, WELLNESS_PLAN, FAMILY_WELLNESS_PLAN),
        **_lock(locks, "wellness_plan"),
        card=card,
    )


def _complete_profile(
    profile: Profile, name: str, locks: Locks, completion: int | None
) -> CompleteHealthProfileWidget:
    """Shown with 6.1's completion percentage until it's 100."""
    return CompleteHealthProfileWidget(
        shown=completion is not None and completion < 100,
        title=_titled(profile, name, COMPLETE_PROFILE, FAMILY_COMPLETE_PROFILE),
        **_lock(locks, "my_health"),
        completion=completion,
    )


def _update_profile(
    db: Session, profile: Profile, name: str, locks: Locks, now: datetime
) -> UpdateHealthProfileWidget:
    """Shown after a provider visit logged since the health profile last changed (5.2), or
    once 3, 6 or 12 months have passed since it did (the largest of those that have), until
    the profile is updated again. The texts are 12.1's notices; 4.1's is the same."""
    fields = {
        "title": _titled(profile, name, UPDATE_PROFILE, FAMILY_UPDATE_PROFILE),
        **_lock(locks, "my_health"),
    }
    last_update = health.last_updated_at(db, profile)
    last_visit = _last_visit_logged_at(db, profile)
    if last_visit is not None and (last_update is None or last_visit > last_update):
        kind = KINDS[health_reminders.REVIEW_AFTER_VISIT]
        text = kind.body if profile.is_self else kind.family_body.replace("[Name]", name)
        return UpdateHealthProfileWidget(
            shown=True, **fields, reason="visit_logged", months=None, message=text
        )
    passed = [
        months
        for months in sorted(settings.health_profile_review_months)
        if last_update is not None and health_reminders.add_months(last_update, months) <= now
    ]
    if not passed:
        return UpdateHealthProfileWidget(
            shown=False, **fields, reason=None, months=None, message=None
        )
    months = passed[-1]
    kind = KINDS[health_reminders.REVIEW]
    template = kind.body if profile.is_self else kind.family_body
    time_text = "1 month" if months == 1 else f"{months} months"
    return UpdateHealthProfileWidget(
        shown=True,
        **fields,
        reason="months",
        months=months,
        message=template.replace("[time]", time_text).replace("[Name]", name),
    )


def _last_visit_logged_at(db: Session, profile: Profile) -> datetime | None:
    """When the profile's latest provider visit was logged (on ix_visit_logs_profile_created)."""
    return db.scalar(select(func.max(VisitLog.created_at)).where(VisitLog.profile_id == profile.id))


def _whats_next(
    db: Session,
    profile: Profile,
    name: str,
    locks: Locks,
    notes: VisitNotesOut | None,
    plan_card: PlanCardOut | None,
) -> WhatsNextWidget:
    """One or two next steps, in the story's order: the soonest upcoming appointment with notes
    ready, the latest past appointment not logged yet, a Wellness Plan item due for a check-in.
    One of each kind comes first; places left go to more of the same kinds. Greyed out with no
    steps while My Visit Notes is locked (the trial)."""
    if notes is None:
        return WhatsNextWidget(
            shown=True, title=WHATS_NEXT, **_lock(locks, "visit_notes"), steps=[]
        )
    groups = [
        [_appointment_step(profile, name, card) for card in notes.cards if card.upcoming],
        [_log_visit_step(profile, name, card) for card in _visits_to_log(notes.cards)],
        _check_in_steps(db, profile, plan_card),
    ]
    limit = settings.home_dashboard_next_steps
    chosen = [(index, 0) for index, group in enumerate(groups) if group][:limit]
    for index, group in enumerate(groups):
        for position in range(1, len(group)):
            if len(chosen) < limit:
                chosen.append((index, position))
    steps = [groups[index][position] for index, position in sorted(chosen)]
    return WhatsNextWidget(
        shown=bool(steps), title=WHATS_NEXT, **_lock(locks, "visit_notes"), steps=steps
    )


def _visits_to_log(cards: list[VisitNoteCard]) -> list[VisitNoteCard]:
    """Notes whose appointment has passed (on Hawaii's date, as My Visit Notes counts it) in
    the last `home_dashboard_log_visit_days`, with no visit logged, latest first."""
    since = us_today() - timedelta(days=settings.home_dashboard_log_visit_days)
    due = [
        card
        for card in cards
        if card.type == "provider_notes"
        and card.can_log_visit
        and not card.upcoming
        and card.appointment_date is not None
        and card.appointment_date >= since
    ]
    return sorted(due, key=lambda card: card.appointment_date, reverse=True)


def _day(day: date) -> str:
    """4.1's "14 Nov"."""
    return f"{day.day} {MONTHS[day.month - 1]}"


def _appointment_step(profile: Profile, name: str, card: VisitNoteCard) -> NextStep:
    fields = {"specialty": card.specialty_label, "day": _day(card.appointment_date)}
    if profile.is_self:
        text = UPCOMING_APPOINTMENT.format(**fields)
    else:
        possessive = POSSESSIVE.get(profile.pronouns or "", "their").capitalize()
        text = FAMILY_UPCOMING_APPOINTMENT.format(name=name, possessive=possessive, **fields)
    return NextStep(
        kind="appointment",
        text=text,
        provider_note_id=card.id,
        appointment_date=card.appointment_date,
        wellness_item_id=None,
    )


def _log_visit_step(profile: Profile, name: str, card: VisitNoteCard) -> NextStep:
    return NextStep(
        kind="log_visit",
        text=LOG_VISIT if profile.is_self else FAMILY_LOG_VISIT.format(name=name),
        provider_note_id=card.id,
        appointment_date=card.appointment_date,
        wellness_item_id=None,
    )


def _check_in_steps(db: Session, profile: Profile, plan_card: PlanCardOut | None) -> list[NextStep]:
    """The plan's open items whose time frame has ended or that are due (7.1's check-ins): the
    ones that make the card's `check_in_due` true, by the same rule."""
    if plan_card is None or not plan_card.check_in_due:
        return []
    plan = wellness.plan_row(db, profile)
    if plan is None:
        return []
    due = today()
    return [
        NextStep(
            kind="plan_check_in",
            text=PLAN_CHECK_IN.format(item=item.title),
            provider_note_id=None,
            appointment_date=None,
            wellness_item_id=item.id,
        )
        for item in wellness.active_items(db, plan)
        if item.follow_up_on is not None and item.follow_up_on <= due and item.status == "open"
    ]


def _visit_notes(locks: Locks, notes: VisitNotesOut | None) -> VisitNotesWidget:
    return VisitNotesWidget(
        shown=True,
        title=VISIT_NOTES,
        **_lock(locks, "visit_notes"),
        notes_count=len(notes.cards) if notes else None,
        upcoming_count=sum(1 for card in notes.cards if card.upcoming) if notes else None,
    )


def _my_health(
    db: Session, profile: Profile, account: User, locks: Locks, completion: int | None
) -> MyHealthWidget:
    pending = None if "my_health" in locks else len(health.list_facts(db, profile, account))
    return MyHealthWidget(
        shown=True,
        title=MY_HEALTH,
        **_lock(locks, "my_health"),
        completion=completion,
        pending_facts=pending,
    )


def _my_family(
    db: Session, profile: Profile, account: User, teen_account: bool, locks: Locks
) -> MyFamilyWidget:
    """Hidden while a family member's profile is active and on a teen's own account. On the
    trial or the Individual plan: the Family plan's upgrade prompt instead."""
    if teen_account or not profile.is_self or "family_members" in locks:
        return MyFamilyWidget(
            shown=not teen_account and profile.is_self,
            title=MY_FAMILY,
            **_lock(locks, None if teen_account else "family_members"),
            members=[],
            invited_teens=[],
            places_used=None,
            places_included=None,
            can_add=False,
        )
    members = [
        member
        for member in profiles.list_profiles(db, account)
        if not member.is_self and member.intake_completed
    ]
    invited = [
        InvitedTeenCard(
            id=card.id,
            first_name=card.first_name,
            relationship=card.relationship,
            status=card.status,
        )
        for card in teens.cards(db, account)
    ]
    used = entitlements.family_members_used(db, account)
    included = entitlements.family_members_included(account)
    return MyFamilyWidget(
        shown=True,
        title=MY_FAMILY,
        **_lock(locks, "family_members"),
        members=members,
        invited_teens=invited,
        places_used=used,
        places_included=included,
        can_add=used < included,
    )
