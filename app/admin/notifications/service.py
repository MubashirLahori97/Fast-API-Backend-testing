"""Admin notifications (Super Admin 11.1, Admin 8.1).

Other code alerts the team with:

    notify_admins(db, "support_request", {"request_type": "consultation"}, target_id=request.id)

It adds one in-app notice per active Admin and the Super Admin (or the Super Admin alone, for
the kinds only they get), and queues each one's email, unless that person turned emails off for
the type. It doesn't commit: the notices are saved with the caller's own changes, and the emails
go out from jobs after that commit. The kinds and their texts are in kinds.py.

A separate package from app/notifications/, which is the Clients' (docs/decisions/
phase-a1-admin-access.md): admins have no profiles, no push, no consent or plan rules, and
their preferences are email on or off per type, with in-app always on.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.notifications import emails
from app.admin.notifications.kinds import (
    AUDIENCE_ROLES,
    CATEGORY_LABELS,
    KINDS,
    LOCKED_CATEGORIES,
    PLACEHOLDERS,
    POLICY_NAMES,
    REQUEST_TYPES,
    SUPER_ADMIN_CATEGORIES,
    TEAM_ROLES,
    Kind,
)
from app.admin.notifications.models import AdminNotification, AdminNotificationPreference
from app.admin.notifications.schemas import (
    AdminNotificationOut,
    AdminNotificationPage,
    AdminPreferenceIn,
    AdminPreferenceOut,
)
from app.auth.models import User
from app.core import jobs
from app.core.config import settings
from app.core.email import EmailSender
from app.core.errors import AppError, database_errors_retryable
from app.core.schemas import clean_line

logger = logging.getLogger(__name__)

EMAIL_JOB = "admin_notifications.email"  # run by app/admin/notifications/jobs.py

# Super Admin 11.1's messages.
ALL_CAUGHT_UP = "You’re all caught up."
CANNOT_TURN_OFF = "Deletion deadline notifications can’t be turned off."
PREFERENCES_UPDATED = "Your notification preferences have been updated."
PREFERENCES_FAILED = "We couldn’t update your preferences just now. Please try again."
# Not in the stories (docs/decisions/phase-a1-admin-access.md).
NOTIFICATION_NOT_FOUND = "We couldn’t find that notification."


def _now() -> datetime:
    return datetime.now(UTC)


def _kind(code: str) -> Kind:
    try:
        return KINDS[code]
    except KeyError:
        raise ValueError(f"Unknown admin notification kind: {code}") from None


# Texts


def _values(kind: Kind, data: dict[str, Any] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in (data or {}).items():
        if key not in PLACEHOLDERS:
            raise ValueError(f"{kind.code} can't take data[{key!r}].")
        if key == "request_type":
            if value not in REQUEST_TYPES:
                raise ValueError(f"Unknown support request type: {value}")
            values[key] = REQUEST_TYPES[value]
        elif key == "policy":
            if value not in POLICY_NAMES:
                raise ValueError(f"Unknown policy kind: {value}")
            values[key] = POLICY_NAMES[value]
        elif key == "question":
            text = clean_line(str(value))
            limit = settings.admin_notification_question_max_length
            if len(text) > limit:
                text = text[: limit - 1].rstrip() + "…"
            if text:
                values[key] = text
        else:
            values[key] = clean_line(str(value))
    missing = [key for key in kind.needs if not values.get(key)]
    if missing:
        raise ValueError(f"{kind.code} needs data for {', '.join(missing)}.")
    return values


def _fill(template: str, values: dict[str, str]) -> str:
    if values.get("days") == "1":
        template = template.replace("[X] days", "1 day")
    for key, value in values.items():
        template = template.replace(PLACEHOLDERS[key], value)
    if any(placeholder in template for placeholder in PLACEHOLDERS.values()):
        raise ValueError(f"A placeholder is left unfilled in {template!r}.")
    return template


# Values a kind gets when the caller doesn't pass them.
_DEFAULTS = {
    "deletion_deadline": lambda: {"days": str(settings.deletion_highlight_days)},
}
# The only values an email may carry: they can't identify a Client or hold health information.
_EMAIL_SAFE = ("policy", "days")


def _choose(template: str, fallback: str | None, values: dict[str, str]) -> str:
    missing = any(
        placeholder in template and key not in values for key, placeholder in PLACEHOLDERS.items()
    )
    return fallback if missing and fallback is not None else template


def _texts(kind: Kind, values: dict[str, str]) -> tuple[str, str]:
    """The in-app body and the email text, each falling back to the kind's general text when
    an optional placeholder (the question, the policy) isn't given."""
    safe = {key: value for key, value in values.items() if key in _EMAIL_SAFE}
    body = _choose(kind.body, kind.fallback_body, values)
    email_text = _choose(kind.email_text, kind.fallback_email_text, safe)
    return _fill(body, values), _fill(email_text, safe)


# Sending


def _recipients(
    db: Session, kind: Kind, super_admin_only: bool, recipient_id: uuid.UUID | None = None
) -> list[User]:
    roles = AUDIENCE_ROLES["super_admin" if super_admin_only else kind.audience]
    query = select(User).where(User.role.in_(roles), User.status == "active")
    if recipient_id is not None:
        query = query.where(User.id == recipient_id)
    return list(db.scalars(query.order_by(User.created_at)))


def _email_choices(db: Session, account_ids: list[uuid.UUID], category: str) -> dict:
    """{account_id: email on?} for the accounts that changed this type; others are on."""
    if not account_ids:
        return {}
    rows = db.execute(
        select(AdminNotificationPreference.account_id, AdminNotificationPreference.email).where(
            AdminNotificationPreference.account_id.in_(account_ids),
            AdminNotificationPreference.category == category,
        )
    )
    return dict(rows.tuples())


def notify_admins(
    db: Session,
    kind: str,
    data: dict[str, Any] | None = None,
    *,
    target_id: uuid.UUID | None = None,
    super_admin_only: bool = False,
    recipient_id: uuid.UUID | None = None,
) -> list[AdminNotification]:
    """Tells the admin team about something that needs their attention (Super Admin 11.1).

    - `kind`: a key of kinds.KINDS: support_request, knowledge_gap, deletion_request,
      deletion_deadline, content_pending_approval, content_approved, content_rejected,
      policy_published, admin_set_up. Escalations aren't notified (11.1), so there's no kind
      for them.
    - `data`: the kind's placeholders, under the keys in kinds.PLACEHOLDERS, e.g.
      {"request_type": "consultation"}, {"question": gap.question}, {"policy": "terms"},
      {"days": 2}. Never a Client's name or email: those stay in the admin panel's own screens.
    - `target_id`: the record the notification opens (see the kind's screen).
    - `super_admin_only`: send it to the Super Admin alone, whatever the kind's audience.
    - `recipient_id`: send it to this one active admin only (Admin 7.1's content decisions).

    Returns the notices added (one per recipient). Doesn't commit."""
    spec = _kind(kind)
    defaults = _DEFAULTS.get(spec.code)
    values = {**(defaults() if defaults else {}), **_values(spec, data)}
    body, email_text = _texts(spec, values)
    recipients = _recipients(db, spec, super_admin_only, recipient_id)
    emails_on = _email_choices(db, [account.id for account in recipients], spec.category)
    created = []
    for account in recipients:
        notification = AdminNotification(
            id=uuid.uuid4(),  # set here, so the job payload can carry it before the flush
            recipient_id=account.id,
            kind=spec.code,
            title=spec.title,
            body=body,
            email_text=email_text,
            screen=spec.screen,
            target_id=target_id,
        )
        db.add(notification)
        if spec.locked or emails_on.get(account.id, True):
            jobs.enqueue(db, EMAIL_JOB, {"notification_id": str(notification.id)})
        created.append(notification)
    return created


def deliver_email(db: Session, payload: dict[str, Any], sender: EmailSender) -> None:
    """Sends one notification's email copy (EMAIL_JOB). Skipped if the recipient has been
    deactivated since, or turned this type's emails off in the meantime."""
    notification = db.get(AdminNotification, uuid.UUID(payload["notification_id"]))
    if notification is None:
        return
    account = db.get(User, notification.recipient_id)
    if account is None or account.status != "active" or account.role not in TEAM_ROLES:
        return
    kind = KINDS.get(notification.kind)
    if kind is None:
        logger.warning("Admin notification of unknown kind %s not emailed", notification.kind)
        return
    if not kind.locked and not _email_choices(db, [account.id], kind.category).get(
        account.id, True
    ):
        return
    sender.send(
        emails.for_notification(
            account.email, kind.title, notification.email_text, can_turn_off=not kind.locked
        )
    )


# The notification centre


def _owned(db: Session, account: User, notification_id: uuid.UUID) -> AdminNotification:
    notification = db.get(AdminNotification, notification_id)
    if notification is None or notification.recipient_id != account.id:
        raise AppError(404, "notification_not_found", NOTIFICATION_NOT_FOUND)
    return notification


def _out(notification: AdminNotification) -> AdminNotificationOut:
    kind = KINDS[notification.kind]  # removing a kind needs a data migration for its rows
    return AdminNotificationOut(
        id=notification.id,
        kind=notification.kind,
        category=kind.category,
        title=notification.title,
        body=notification.body,
        screen=notification.screen,
        target_id=notification.target_id,
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


def unread_count(db: Session, account: User) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AdminNotification)
        .where(AdminNotification.recipient_id == account.id, AdminNotification.read_at.is_(None))
    )


def list_notifications(
    db: Session, account: User, before: uuid.UUID | None, limit: int
) -> AdminNotificationPage:
    """11.1's notification centre: newest first, a page at a time. `before` is the last id of
    the previous page."""
    stmt = select(AdminNotification).where(AdminNotification.recipient_id == account.id)
    if before is not None:
        cursor = _owned(db, account, before)
        stmt = stmt.where(
            tuple_(AdminNotification.created_at, AdminNotification.id)
            < (cursor.created_at, cursor.id)
        )
    rows = list(
        db.scalars(
            stmt.order_by(AdminNotification.created_at.desc(), AdminNotification.id.desc()).limit(
                limit + 1
            )
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    items = [_out(row) for row in rows]
    return AdminNotificationPage(
        items=items,
        unread_count=unread_count(db, account),
        next_before=rows[-1].id if more else None,
        message=ALL_CAUGHT_UP if not items and before is None else None,
    )


def open_notification(
    db: Session, account: User, notification_id: uuid.UUID
) -> AdminNotificationOut:
    """The admin selected a notification: it's marked read, and the panel gets the screen and
    record to open. A resolved item shows as resolved on its own screen (11.1)."""
    notification = _owned(db, account, notification_id)
    if notification.read_at is None:
        notification.read_at = _now()
        with database_errors_retryable(db):
            db.commit()
    return _out(notification)


def mark_all_read(db: Session, account: User) -> None:
    with database_errors_retryable(db):
        db.execute(
            update(AdminNotification)
            .where(
                AdminNotification.recipient_id == account.id,
                AdminNotification.read_at.is_(None),
            )
            .values(read_at=_now())
        )
        db.commit()


# Preferences


def _categories_for(account: User) -> list[str]:
    """The types this person receives: Admins don't get new-Admin set-ups (11.1)."""
    return [
        category
        for category in CATEGORY_LABELS
        if account.role == "super_admin" or category not in SUPER_ADMIN_CATEGORIES
    ]


def get_preferences(db: Session, account: User) -> list[AdminPreferenceOut]:
    chosen = dict(
        db.execute(
            select(AdminNotificationPreference.category, AdminNotificationPreference.email).where(
                AdminNotificationPreference.account_id == account.id
            )
        ).tuples()
    )
    return [
        AdminPreferenceOut(
            category=category,
            label=CATEGORY_LABELS[category],
            email=True if category in LOCKED_CATEGORIES else chosen.get(category, True),
            can_turn_off=category not in LOCKED_CATEGORIES,
        )
        for category in _categories_for(account)
    ]


def update_preferences(
    db: Session, account: User, changes: list[AdminPreferenceIn]
) -> list[AdminPreferenceOut]:
    """Saves the choices straight away, for every device (11.1). The deletion deadline type is
    accepted only unchanged (email on), so the panel can send the whole screen."""
    allowed = set(_categories_for(account))
    for change in changes:
        if change.category in LOCKED_CATEGORIES and not change.email:
            raise AppError(422, "cannot_turn_off", CANNOT_TURN_OFF, "preferences")
        if change.category not in allowed:
            raise AppError(
                422, "unknown_category", "This notification type isn’t available.", "preferences"
            )
    try:
        for change in changes:
            if change.category in LOCKED_CATEGORIES:
                continue
            stmt = insert(AdminNotificationPreference).values(
                account_id=account.id, category=change.category, email=change.email
            )
            db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["account_id", "category"],
                    set_={"email": stmt.excluded.email, "updated_at": func.now()},
                )
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", PREFERENCES_FAILED) from None
    return get_preferences(db, account)
