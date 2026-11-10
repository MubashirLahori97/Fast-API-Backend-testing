"""Notifications (story 12.1): the one way every phase tells a client something.

Other phases call:

- `notify(db, account, kind, profile=..., target_id=..., data=...)` to send a notice now;
- `schedule(db, account, kind, run_at, ...)` for reminders, and `cancel_scheduled(...)` when
  what a reminder is about changes (an appointment date) or goes away.

Both apply the client's preferences and the story's "when not to send" rules; a scheduled
reminder is checked again when it's due. Neither commits: the notice is saved with the caller's
own changes, and its push and email copies go out from jobs after that commit.

The kinds and their texts are in kinds.py.
"""

import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, object_session

from app.accounts.models import (
    OPEN_DELETION_STATUSES,
    ConsentRevocation,
    DeletionRequest,
    PolicyAcceptance,
    PolicyVersion,
)
from app.auth.models import User, UserSession
from app.auth.security import hash_secret

# The module, not the function: Phase 3b's teen notice will make safety.py import this module,
# and a module import still works inside that cycle.
from app.conversations import safety
from app.core import jobs
from app.core.config import settings
from app.core.email import EmailSender
from app.core.errors import AppError, database_errors_retryable
from app.core.jobs import Job
from app.core.push import InvalidPushToken, PushMessage, PushSender
from app.notifications import emails, targets
from app.notifications.kinds import (
    CATEGORY_LABELS,
    DETAIL_PLACEHOLDERS,
    GENERAL_UPDATE,
    KINDS,
    LOCKED_CATEGORIES,
    PLACEHOLDERS,
    SCHEDULE_OPTIONS,
    Kind,
)
from app.notifications.models import Notification, NotificationPreference, PushToken
from app.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    PreferenceIn,
    PreferenceOut,
    PushTokenIn,
)
from app.privacy import teens
from app.profiles.models import Profile

logger = logging.getLogger(__name__)

# Job kinds, run by app/notifications/jobs.py.
SEND_JOB = "notifications.send"  # a scheduled reminder
PUSH_JOB = "notifications.push"  # the push copies of one notification
EMAIL_JOB = "notifications.email"  # the email copy of one notification
SWEEP_JOB = "notifications.sweep"  # trial reminders and inactivity check-ins, every minute
ANNOUNCE_POLICY_JOB = "notifications.announce_policy_version"  # a version published for later
POLICY_EMAILS_JOB = "notifications.policy_update_emails"  # queues one batch of clients
POLICY_EMAIL_JOB = "notifications.policy_update_email"  # emails one client
# Key for pg_advisory_xact_lock, so two workers starting at once don't both start a sweep.
SWEEP_LOCK_KEY = 9_120_401

# Story 12.1's messages.
ALL_CAUGHT_UP = "You’re all caught up."
ITEM_UNAVAILABLE = "This item is no longer available."
CANNOT_TURN_OFF = (
    "These notifications keep you safe and your account up to date, so they can’t be turned off."
)
PREFERENCES_UPDATED = "Your notification preferences have been updated."
PREFERENCES_FAILED = "We couldn’t update your preferences just now. Please try again."
# Not in the stories (docs/decisions/phase-9-notifications.md).
NOTIFICATION_NOT_FOUND = "We couldn’t find that notification."
PUSH_TOKEN_NOT_FOUND = "We couldn’t find that device."
PUSH_TITLE = "Your Oracle"

# Sessions that ended on their own: the device is still the client's, so it keeps getting
# pushes. A sign-out, password reset, policy update or deactivation stops them.
TIMED_OUT = ("session_expired", "signed_out_inactive")
_UNFILLED = re.compile(r"\[(Name|X|time|new email)\]")
_DETAILS = re.compile(r"\[(topic|specialty)\]")


class PushNotSent(Exception):
    """Every device's push failed for a reason worth retrying, so the worker tries again."""


def _now() -> datetime:
    return datetime.now(UTC)


def _kind(code: str) -> Kind:
    try:
        return KINDS[code]
    except KeyError:
        raise ValueError(f"Unknown notification kind: {code}") from None


def _client_conditions() -> tuple[ColumnElement[bool], ...]:
    """The accounts the sweeps and policy emails go to. Teen accounts are left out: they have no
    trial, 12.1 gives them no inactivity check-in, and 12.2 says they aren't shown the policy
    update (the parent accepts it for them). Their own reminders still go to them (12.1)."""
    return (User.role == "client", User.status == "active", User.account_type == "adult")


# When not to send (12.1)


def consent_revoked(account: User) -> bool:
    """Story 11.4: once a client revokes consent, all their notifications stop until they give
    it again. Once a request to delete the whole account is past its 10-day grace period (the
    account is locked), they stop too; during the grace period everything works as normal,
    notices included. The same rule as `accounts.service.consent_withdrawn` (an invited teen
    locked by the parent's deletion is covered by teens.lost_access), queried here because that
    module imports this one.

    It reads through the account's own database session, so callers needn't pass one."""
    db = object_session(account)
    if db is None:
        raise ValueError("The account isn't loaded in a database session.")
    revoked = exists().where(
        ConsentRevocation.account_id == account.id, ConsentRevocation.restored_at.is_(None)
    )
    deleting = exists().where(
        DeletionRequest.account_id == account.id,
        DeletionRequest.profile_id.is_(None),
        DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        DeletionRequest.locked_at.is_not(None),
    )
    return bool(db.scalar(select(revoked | deleting)))


def after_emergency_or_crisis(db: Session, account: User, profile: Profile | None) -> bool:
    """Story 3.2: "the platform doesn't follow up, call or send check-ins after an emergency or
    crisis". Asks the conversations package (`safety.check_ins_blocked`), which says whether an
    emergency or crisis was ever detected for the profile. With no profile (the inactivity
    check-in, which is about the client), any of the account's profiles counts.

    It's asked for the whole profile, with no time limit, until question 28 says which notices
    stop and for how long (docs/decisions/phase-9-notifications.md)."""
    if profile is not None:
        return safety.check_ins_blocked(db, profile_id=profile.id)
    profile_ids = db.scalars(select(Profile.id).where(Profile.account_id == account.id)).all()
    return any(safety.check_ins_blocked(db, profile_id=profile_id) for profile_id in profile_ids)


def may_notify(account: User) -> bool:
    """Whether the account gets any notifications at all."""
    return account.status == "active" and not consent_revoked(account)


def _usable(profile: Profile) -> bool:
    """12.1: never for turned-off or deleted family members (8.2 also pauses their reminders
    while turned off, and cancels them once deletion is asked for)."""
    return (
        profile.intake_completed_at is not None
        and profile.turned_off_at is None
        and profile.deletion_requested_at is None
    )


def _may_send(db: Session, account: User, kind: Kind, profile: Profile | None) -> bool:
    if not may_notify(account):
        return False
    if kind.category != "teen_safety_access" and teens.lost_access(db, account):
        # A teen whose access is paused (or who has reached adult age) gets only their access
        # and age notices: their reminders stop with the parent's consent or plan (11.4, 1.5).
        return False
    if profile is not None and not _usable(profile):
        return False
    return not (kind.check_in and after_emergency_or_crisis(db, account, profile))


# Preferences


@dataclass(frozen=True)
class Channels:
    enabled: bool
    push: bool
    email: bool


# The types that can't be turned off go everywhere.
LOCKED_CHANNELS = Channels(enabled=True, push=True, email=True)


def _default_channels() -> Channels:
    return Channels(enabled=True, push=True, email=settings.notification_email_by_default)


def channels(db: Session, account: User, category: str) -> Channels:
    """Where notices of this type go for this account."""
    if category in LOCKED_CATEGORIES:
        return LOCKED_CHANNELS
    row = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.account_id == account.id,
            NotificationPreference.category == category,
        )
    )
    if row is None:
        return _default_channels()
    return Channels(enabled=row.enabled, push=row.push, email=row.email)


def get_preferences(db: Session, account: User) -> list[PreferenceOut]:
    """Every type, in the story's order, including the ones that can't be turned off."""
    rows = {
        row.category: row
        for row in db.scalars(
            select(NotificationPreference).where(NotificationPreference.account_id == account.id)
        )
    }
    result = []
    for category, label in CATEGORY_LABELS.items():
        if category in LOCKED_CATEGORIES:
            chosen = LOCKED_CHANNELS
        elif category in rows:
            row = rows[category]
            chosen = Channels(enabled=row.enabled, push=row.push, email=row.email)
        else:
            chosen = _default_channels()
        result.append(
            PreferenceOut(
                category=category,
                label=label,
                enabled=chosen.enabled,
                push=chosen.push,
                email=chosen.email,
                can_turn_off=category not in LOCKED_CATEGORIES,
            )
        )
    return result


def update_preferences(
    db: Session, account: User, changes: list[PreferenceIn]
) -> list[PreferenceOut]:
    """Saves the client's choices straight away (12.1). A type that can't be turned off is
    accepted only unchanged, so the app can send the whole screen."""
    for change in changes:
        if change.category in LOCKED_CATEGORIES and not (
            change.enabled and change.push and change.email
        ):
            raise AppError(422, "cannot_turn_off", CANNOT_TURN_OFF, "preferences")
    try:
        for change in changes:
            if change.category in LOCKED_CATEGORIES:
                continue
            stmt = insert(NotificationPreference).values(
                account_id=account.id,
                category=change.category,
                enabled=change.enabled,
                push=change.push,
                email=change.email,
            )
            db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["account_id", "category"],
                    set_={
                        "enabled": stmt.excluded.enabled,
                        "push": stmt.excluded.push,
                        "email": stmt.excluded.email,
                        "updated_at": func.now(),
                    },
                )
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", PREFERENCES_FAILED) from None
    return get_preferences(db, account)


# Texts


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        placeholder = PLACEHOLDERS.get(key) or DETAIL_PLACEHOLDERS[key]
        if key == "days" and value == "1":
            template = template.replace("[X] days", "1 day")
        template = template.replace(placeholder, value)
    return template


def _is_family(profile: Profile | None) -> bool:
    return profile is not None and not profile.is_self


def _values(kind: Kind, profile: Profile | None, data: dict[str, Any] | None) -> dict[str, str]:
    """The placeholders filled when the notice is created. Only first names and the kinds'
    options: [topic] and [specialty] are health data and are never passed in."""
    values: dict[str, str] = {}
    if _is_family(profile):
        values["name"] = profile.first_name or ""
    for key, value in (data or {}).items():
        if key not in PLACEHOLDERS:
            raise ValueError(f"{kind.code} can't take data[{key!r}].")
        values[key] = str(value)
    missing = [key for key in kind.needs if key not in values]
    if missing:
        raise ValueError(f"{kind.code} needs data for {', '.join(missing)}.")
    return values


def _render(template: str, values: dict[str, str], kind: Kind) -> str:
    text = _fill(template, values)
    if _UNFILLED.search(text):
        raise ValueError(f"{kind.code} has a placeholder left unfilled.")
    return text


def _generic(kind: Kind, profile: Profile | None) -> str:
    """The text shown when [topic] or [specialty] can't be filled any more."""
    template = kind.generic_family_body if _is_family(profile) else kind.generic_body
    if template is None:
        return GENERAL_UPDATE
    return _fill(template, {"name": profile.first_name or ""} if _is_family(profile) else {})


# Sending


def _push_tokens(db: Session, account_id: uuid.UUID) -> list[PushToken]:
    """The account's devices that get pushes: their session is active or only timed out."""
    return list(
        db.scalars(
            select(PushToken)
            .join(UserSession, PushToken.session_id == UserSession.id)
            .where(
                PushToken.account_id == account_id,
                or_(UserSession.revoked_at.is_(None), UserSession.revoked_reason.in_(TIMED_OUT)),
            )
        )
    )


def notify(
    db: Session,
    account: User,
    kind: str,
    *,
    profile: Profile | None = None,
    target_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> Notification | None:
    """Sends a notice now: adds it to the notification centre, and queues its push and email
    copies for after the caller commits. Returns None when nothing is sent: preferences, a
    turned-off or deleted family member, revoked consent, or a check-in after an emergency or
    crisis (12.1, 3.2).

    - `profile`: the profile it's about. A family member's first name fills [Name].
    - `target_id`: the record it opens (see the kind's `target`).
    - `data`: values for the kind's other placeholders, under the keys in kinds.PLACEHOLDERS,
      e.g. {"days": 3} or {"name": "Azka"} when the member's profile is gone or the notice is
      about a teen's own account. Never health data.
    """
    spec = _kind(kind)
    if profile is not None and profile.account_id != account.id:
        raise ValueError("The profile isn't this account's.")
    if not _may_send(db, account, spec, profile):
        return None
    chosen = channels(db, account, spec.category)
    if not chosen.enabled:
        return None

    values = _values(spec, profile, data)
    template = spec.family_body if _is_family(profile) and spec.family_body else spec.body
    notification = Notification(
        id=uuid.uuid4(),  # set here, so the job payloads can carry it before the flush
        account_id=account.id,
        profile_id=profile.id if profile is not None else None,
        kind=kind,
        title=spec.title,
        body=_render(template, values, spec),
        outside_text=_render(spec.outside or GENERAL_UPDATE, values, spec),
        screen=spec.screen,
        target_id=target_id,
    )
    db.add(notification)
    payload = {"notification_id": str(notification.id)}
    if chosen.push and _push_tokens(db, account.id):
        jobs.enqueue(db, PUSH_JOB, payload)
    if chosen.email:
        jobs.enqueue(db, EMAIL_JOB, payload)
    return notification


def schedule(
    db: Session,
    account: User,
    kind: str,
    run_at: datetime,
    *,
    profile: Profile | None = None,
    target_id: uuid.UUID | None = None,
    data: dict[str, str | int] | None = None,
) -> Job | None:
    """Sends `kind` at `run_at`, through a job. Every rule is checked again then, and nothing is
    sent if the profile or the target record is gone. Caller commits.

    A follow-up or check-in about a profile that has had an emergency or crisis isn't scheduled
    at all (returns None), and one scheduled before is dropped when it's due (3.2).

    `data` goes into the job payload, so it may hold only the options in
    kinds.SCHEDULE_OPTIONS (e.g. {"time": "6 months"}); names are looked up from the profile
    when it's sent. To move a reminder, cancel_scheduled() it and schedule it again."""
    spec = _kind(kind)
    if profile is not None and profile.account_id != account.id:
        raise ValueError("The profile isn't this account's.")
    if spec.check_in and after_emergency_or_crisis(db, account, profile):
        return None
    options = {}
    for key, value in (data or {}).items():
        if key not in SCHEDULE_OPTIONS:
            raise ValueError(f"data[{key!r}] can't go into a job payload.")
        options[key] = str(value)
    missing = [key for key in spec.needs if key not in options]
    if missing:
        raise ValueError(f"{kind} needs data for {', '.join(missing)}.")
    payload: dict[str, Any] = {"account_id": str(account.id), "kind": kind}
    if profile is not None:
        payload["profile_id"] = str(profile.id)
    if target_id is not None:
        payload["target_id"] = str(target_id)
    if options:
        payload["options"] = options
    return jobs.enqueue(db, SEND_JOB, payload, run_at=run_at)


def cancel_scheduled(
    db: Session,
    account: User,
    *,
    kind: str | None = None,
    profile: Profile | None = None,
    target_id: uuid.UUID | None = None,
) -> int:
    """Cancels the account's reminders that are still waiting, narrowed by kind, profile or
    target record. Returns how many were cancelled. Caller commits."""
    match: dict[str, str] = {"account_id": str(account.id)}
    if kind is not None:
        match["kind"] = _kind(kind).code
    if profile is not None:
        match["profile_id"] = str(profile.id)
    if target_id is not None:
        match["target_id"] = str(target_id)
    result = db.execute(
        delete(Job).where(
            Job.kind == SEND_JOB, Job.status == "pending", Job.payload.contains(match)
        )
    )
    return result.rowcount


def send_scheduled(db: Session, payload: dict[str, Any]) -> None:
    """Runs one scheduled reminder (SEND_JOB). The worker commits."""
    account = db.get(User, uuid.UUID(payload["account_id"]))
    if account is None:
        return  # the account was deleted
    kind = KINDS.get(payload["kind"])
    if kind is None:
        logger.warning("Scheduled notification of unknown kind %s skipped", payload["kind"])
        return
    profile = None
    if payload.get("profile_id"):
        profile = db.get(Profile, uuid.UUID(payload["profile_id"]))
        if profile is None or profile.account_id != account.id:
            return  # deleted, or moved to another account (11.4's transfer)
    target_id = uuid.UUID(payload["target_id"]) if payload.get("target_id") else None
    target = targets.look_up(db, kind.target, target_id, profile.id if profile else None)
    if not target.exists:
        return  # what it was about is gone
    notify(
        db, account, kind.code, profile=profile, target_id=target_id, data=payload.get("options")
    )


def deliver_push(db: Session, payload: dict[str, Any], sender: PushSender) -> None:
    """Sends a notification's push to each of the account's devices (PUSH_JOB). A device whose
    token no longer works is forgotten. If every device failed for another reason, it raises,
    so the worker retries; if some got it, the others aren't retried, so nobody gets it twice."""
    notification = db.get(Notification, uuid.UUID(payload["notification_id"]))
    if notification is None or notification.read_at is not None:
        return  # deleted with its profile, or already seen in the app
    account = db.get(User, notification.account_id)
    if account is None or not may_notify(account):
        return
    sent = failed = 0
    for token in _push_tokens(db, account.id):
        message = PushMessage(
            token=token.token,
            title=PUSH_TITLE,
            body=notification.outside_text,
            data={"notification_id": str(notification.id)},
        )
        try:
            sender.send(message)
        except InvalidPushToken:
            db.delete(token)
            continue
        except Exception as exc:
            failed += 1
            # The class name only, as everywhere: provider errors can echo the message back.
            logger.warning(
                "Push for notification %s failed: %s", notification.id, type(exc).__name__
            )
            continue
        sent += 1
    if failed and not sent:
        raise PushNotSent


def deliver_email(db: Session, payload: dict[str, Any], sender: EmailSender) -> None:
    """Sends a notification's email copy (EMAIL_JOB), with its general text only."""
    notification = db.get(Notification, uuid.UUID(payload["notification_id"]))
    if notification is None:
        return
    account = db.get(User, notification.account_id)
    if account is None or not may_notify(account):
        return
    kind = KINDS.get(notification.kind)
    subject = kind.title if kind is not None and kind.outside is not None else GENERAL_UPDATE
    sender.send(emails.for_notification(account.email, subject, notification.outside_text))


# Reminders this package sends itself: the trial and inactivity (12.1)


def ensure_sweep(db: Session, run_at: datetime | None = None) -> None:
    """Makes sure one sweep is waiting to run. Caller commits."""
    db.execute(select(func.pg_advisory_xact_lock(SWEEP_LOCK_KEY)))
    waiting = db.scalar(
        select(Job.id).where(Job.kind == SWEEP_JOB, Job.status == "pending").limit(1)
    )
    if waiting is None:
        jobs.enqueue(db, SWEEP_JOB, run_at=run_at)


def run_sweep(db: Session, now: datetime) -> None:
    """One run of the reminder sweep. The worker commits."""
    send_trial_reminders(db, now)
    send_inactivity_check_ins(db, now)


def _not_sent_since(kind: str, since: ColumnElement[datetime]) -> ColumnElement[bool]:
    return ~exists().where(
        Notification.account_id == User.id,
        Notification.kind == kind,
        Notification.created_at >= since,
    )


def send_trial_reminders(db: Session, now: datetime) -> None:
    """9.1 and 12.1: a reminder before the free trial ends, and one when it has ended. Each is
    sent once per trial end date. The day's slack in the checks covers clock differences
    between the app and the database."""
    lead = timedelta(days=settings.trial_ending_reminder_days)
    slack = timedelta(days=1)
    on_trial = User.subscription_plan.is_(None)
    ending = (
        select(User)
        .where(
            *_client_conditions(),
            on_trial,
            User.trial_ends_at > now,
            User.trial_ends_at <= now + lead,
            _not_sent_since("trial_ending", User.trial_ends_at - lead - slack),
        )
        .order_by(User.trial_ends_at)
        .limit(settings.reminder_sweep_batch_size)
    )
    for account in db.scalars(ending).all():
        days = max(1, math.ceil((account.trial_ends_at - now) / timedelta(days=1)))
        notify(db, account, "trial_ending", data={"days": days})

    ended = (
        select(User)
        .where(
            *_client_conditions(),
            on_trial,
            User.trial_ends_at <= now,
            # Trials that ended while the worker was down are caught up, older ones aren't.
            User.trial_ends_at > now - timedelta(days=settings.reminder_catch_up_days),
            _not_sent_since("trial_ended", User.trial_ends_at - slack),
        )
        .order_by(User.trial_ends_at)
        .limit(settings.reminder_sweep_batch_size)
    )
    for account in db.scalars(ended).all():
        notify(db, account, "trial_ended")


def send_inactivity_check_ins(db: Session, now: datetime) -> None:
    """12.1: "a check-in after 30 days without using the app", once per quiet spell. Using the
    app is the account's latest session activity (sessions.last_seen_at)."""
    quiet = timedelta(days=settings.inactivity_check_in_days)
    last_seen = (
        select(func.max(UserSession.last_seen_at))
        .where(UserSession.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    last_active = func.coalesce(last_seen, User.created_at)
    turned_off = exists().where(
        NotificationPreference.account_id == User.id,
        NotificationPreference.category == "inactivity",
        NotificationPreference.enabled.is_(False),
    )
    stmt = (
        select(User)
        .where(
            *_client_conditions(),
            last_active <= now - quiet,
            last_active > now - quiet - timedelta(days=settings.reminder_catch_up_days),
            _not_sent_since("inactivity_check_in", last_active),
            ~turned_off,
        )
        .limit(settings.reminder_sweep_batch_size)
    )
    for account in db.scalars(stmt).all():
        # About the client, not one profile: it opens a new conversation on the active one.
        notify(db, account, "inactivity_check_in")


# Policy updates (12.2): the emails. Ending sessions is accounts.service.announce_policy_version.


def start_policy_update_emails(db: Session, policy: PolicyVersion) -> None:
    """Queues the first batch of 12.2's update emails. Caller commits."""
    jobs.enqueue(db, POLICY_EMAILS_JOB, {"policy_version_id": str(policy.id)})


def queue_policy_update_emails(db: Session, payload: dict[str, Any]) -> None:
    """One batch (POLICY_EMAILS_JOB): an email job per client, then the next batch. Clients who
    signed up after the version was published accepted it at sign-up, so they're left out."""
    policy = db.get(PolicyVersion, uuid.UUID(payload["policy_version_id"]))
    if policy is None:
        return
    stmt = (
        select(User.id)
        .where(*_client_conditions(), User.created_at < policy.published_at)
        .order_by(User.id)
        .limit(settings.policy_email_batch_size)
    )
    if payload.get("after_account_id"):
        stmt = stmt.where(User.id > uuid.UUID(payload["after_account_id"]))
    account_ids = list(db.scalars(stmt))
    for account_id in account_ids:
        jobs.enqueue(
            db,
            POLICY_EMAIL_JOB,
            {"policy_version_id": str(policy.id), "account_id": str(account_id)},
        )
    if len(account_ids) == settings.policy_email_batch_size:
        jobs.enqueue(
            db,
            POLICY_EMAILS_JOB,
            {"policy_version_id": str(policy.id), "after_account_id": str(account_ids[-1])},
        )


def send_policy_update_email(db: Session, payload: dict[str, Any], sender: EmailSender) -> None:
    """Emails one client about an updated policy (POLICY_EMAIL_JOB), unless they've already
    accepted it or their notifications have stopped (revoked consent)."""
    policy = db.get(PolicyVersion, uuid.UUID(payload["policy_version_id"]))
    account = db.get(User, uuid.UUID(payload["account_id"]))
    if policy is None or account is None or not may_notify(account):
        return
    accepted = db.scalar(
        select(PolicyAcceptance.id).where(
            PolicyAcceptance.user_id == account.id,
            PolicyAcceptance.policy_version_id == policy.id,
        )
    )
    if accepted is None:
        sender.send(emails.policy_updated(account.email, policy.title))


# The notification centre


def _owned(db: Session, account: User, notification_id: uuid.UUID) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.account_id != account.id:
        raise AppError(404, "notification_not_found", NOTIFICATION_NOT_FOUND)
    return notification


def _out(
    db: Session,
    account: User,
    notification: Notification,
    profile: Profile | None,
    target: targets.Target | None = None,
) -> NotificationOut:
    """The notice as the app shows it, with [topic] or [specialty] filled from the record it
    links to, or the kind's generic text when that's gone."""
    kind = KINDS[notification.kind]  # removing a kind needs a data migration for its rows
    body = notification.body
    if _DETAILS.search(body):
        if target is None:
            target = targets.look_up(
                db, kind.target, notification.target_id, notification.profile_id
            )
        body = _fill(body, target.details)
        if _DETAILS.search(body):
            body = _generic(kind, profile)
    if profile is None:
        profile_name = None
    elif profile.is_self:
        profile_name = account.first_name
    else:
        profile_name = profile.first_name
    return NotificationOut(
        id=notification.id,
        kind=notification.kind,
        category=kind.category,
        title=notification.title,
        body=body,
        profile_id=notification.profile_id,
        profile_name=profile_name,
        screen=notification.screen,
        target_id=notification.target_id,
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


def unread_count(db: Session, account: User) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.account_id == account.id, Notification.read_at.is_(None))
    )


def list_notifications(
    db: Session, account: User, before: uuid.UUID | None, limit: int
) -> NotificationPage:
    """12.1's notification centre: newest first, a page at a time. `before` is the last id of
    the previous page."""
    stmt = select(Notification).where(Notification.account_id == account.id)
    if before is not None:
        cursor = _owned(db, account, before)
        stmt = stmt.where(
            tuple_(Notification.created_at, Notification.id) < (cursor.created_at, cursor.id)
        )
    rows = list(
        db.scalars(
            stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    profile_ids = {row.profile_id for row in rows if row.profile_id is not None}
    profiles = (
        {p.id: p for p in db.scalars(select(Profile).where(Profile.id.in_(profile_ids)))}
        if profile_ids
        else {}
    )
    items = [_out(db, account, row, profiles.get(row.profile_id)) for row in rows]
    return NotificationPage(
        items=items,
        unread_count=unread_count(db, account),
        next_before=rows[-1].id if more else None,
        message=ALL_CAUGHT_UP if not items and before is None else None,
    )


def open_notification(db: Session, account: User, notification_id: uuid.UUID) -> NotificationOut:
    """The client tapped a notification: it's marked read, and the app gets where to go. If
    what it's about no longer exists, or its profile can't be used any more, the story's
    message is returned instead (410), after marking it read."""
    notification = _owned(db, account, notification_id)
    if notification.read_at is None:
        notification.read_at = _now()
        with database_errors_retryable(db):
            db.commit()
    kind = KINDS[notification.kind]
    profile = db.get(Profile, notification.profile_id) if notification.profile_id else None
    target = targets.look_up(db, kind.target, notification.target_id, notification.profile_id)
    if (profile is not None and not _usable(profile)) or not target.exists:
        raise AppError(410, "item_unavailable", ITEM_UNAVAILABLE)
    return _out(db, account, notification, profile, target)


def mark_all_read(db: Session, account: User) -> None:
    with database_errors_retryable(db):
        db.execute(
            update(Notification)
            .where(Notification.account_id == account.id, Notification.read_at.is_(None))
            .values(read_at=_now())
        )
        db.commit()


# Push devices


def register_push_token(db: Session, session: UserSession, data: PushTokenIn) -> PushToken:
    """Adds this device, or moves its token to this session and account: a phone that another
    account used before gets this account's pushes only. Keeps the newest few per account."""
    with database_errors_retryable(db):
        stmt = insert(PushToken).values(
            account_id=session.user_id,
            session_id=session.id,
            platform=data.platform,
            token=data.token,
            token_hash=hash_secret(data.token),
        )
        token_id = db.scalar(
            stmt.on_conflict_do_update(
                index_elements=["token_hash"],
                set_={
                    "account_id": stmt.excluded.account_id,
                    "session_id": stmt.excluded.session_id,
                    "platform": stmt.excluded.platform,
                    "updated_at": func.now(),
                },
            ).returning(PushToken.id)
        )
        oldest = (
            select(PushToken.id)
            .where(PushToken.account_id == session.user_id)
            .order_by(PushToken.updated_at.desc(), PushToken.id)
            .offset(settings.max_push_tokens_per_account)
        )
        db.execute(delete(PushToken).where(PushToken.id.in_(oldest)))
        db.commit()
        return db.get(PushToken, token_id)


def remove_push_token(db: Session, account: User, token_id: uuid.UUID) -> None:
    """The device stops getting pushes, e.g. when the client turns them off in the app."""
    token = db.get(PushToken, token_id)
    if token is None or token.account_id != account.id:
        raise AppError(404, "push_token_not_found", PUSH_TOKEN_NOT_FOUND)
    with database_errors_retryable(db):
        db.delete(token)
        db.commit()
