"""Audit Logs (Super Admin 10.1). Super Admin only since the 6 Nov 19:22 stories (the router uses
SuperAdminSession); the Admin rules below are kept but no Admin reaches them now.

Entries show the date and time, who (name and role), the action, what it affected, and the
device and IP address for sign-in events, newest first. They never show an event's `details`
(field names there could hint at health information), except the reason given for a
deactivation or reactivation. Admins see everything the Super Admin sees except Clients'
subscription events (Super Admin 7.2).
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime

from fastapi import Request
from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.audit.catalog import (
    CATEGORY_LABELS,
    ROLE_LABELS,
    SUPER_ADMIN_ONLY_CATEGORIES,
    category_condition,
    category_of,
    label_of,
)
from app.admin.audit.schemas import (
    AuditActor,
    AuditEntryOut,
    AuditFilterOptions,
    AuditFilters,
    AuditOption,
    AuditPage,
    AuditSearch,
    AuditTarget,
)
from app.admin.auth.models import AdminInvitation
from app.auth.models import User
from app.core import audit
from app.core.ages import age_of_majority, is_adult, us_today, years_before
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.errors import AppError

# Super Admin 10.1's messages.
NO_RESULTS = "No entries match your filters."
EXPORT_TOO_LARGE = "This export is too large. Please choose a shorter date range."
EXPORT_FAILED = "We couldn’t export the audit logs. Please try again."

# Actions whose reason is shown (a free-text reason the Super Admin or an Admin typed).
_REASON_SUFFIXES = (".deactivated", ".reactivated")
_BATCH = 1000


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def filter_options(viewer: User) -> AuditFilterOptions:
    return AuditFilterOptions(
        categories=[
            AuditOption(code=code, label=label)
            for code, label in CATEGORY_LABELS.items()
            if viewer.role == "super_admin" or code not in SUPER_ADMIN_ONLY_CATEGORIES
        ],
        roles=[AuditOption(code=code, label=label) for code, label in ROLE_LABELS.items()],
    )


# Filters


def _matching_people(term: str) -> ColumnElement[bool]:
    """10.1's search by name or email: entries by that person, or about their account or their
    Admin invite."""
    pattern = _like(term)
    full_name = User.first_name + " " + func.coalesce(User.last_name, "")
    users = or_(
        User.first_name.ilike(pattern),
        User.last_name.ilike(pattern),
        User.email.ilike(pattern),
        full_name.ilike(pattern),
    )
    invite_name = AdminInvitation.first_name + " " + AdminInvitation.last_name
    invites = or_(AdminInvitation.email.ilike(pattern), invite_name.ilike(pattern))
    return or_(
        AuditEvent.actor_id.in_(select(User.id).where(users)),
        and_(
            AuditEvent.target_type == "user",
            AuditEvent.target_id.in_(select(cast(User.id, String)).where(users)),
        ),
        and_(
            AuditEvent.target_type == "admin_invitation",
            AuditEvent.target_id.in_(select(cast(AdminInvitation.id, String)).where(invites)),
        ),
    )


def _system() -> ColumnElement[bool]:
    return and_(AuditEvent.actor_id.is_(None), AuditEvent.ip_address.is_(None))


def _adult_by() -> ColumnElement[date]:
    """SQL: the latest date of birth that has reached the age of majority today, in the
    account's own state (19 in Alabama and Nebraska, 21 in Mississippi, 18 elsewhere)."""
    day = us_today()
    default = years_before(day, age_of_majority(None))
    whens = [
        (User.state == state, years_before(day, age_of_majority(state)))
        for state in settings.age_of_majority_by_state
    ]
    return case(*whens, else_=default) if whens else literal(default)


def _role_condition(role: str) -> ColumnElement[bool]:
    def actors(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
        return AuditEvent.actor_id.in_(select(User.id).where(*conditions))

    # Teens are account holders under the age of majority (invited teens, Phase 3b).
    adult_by = _adult_by()
    if role == "client":
        return actors(
            User.role == "client",
            or_(User.date_of_birth.is_(None), User.date_of_birth <= adult_by),
        )
    if role == "teen":
        return actors(User.role == "client", User.date_of_birth > adult_by)
    if role in ("admin", "super_admin"):
        return actors(User.role == role)
    if role == "system":
        return _system()
    # anonymous: a request from someone with no account (yet)
    return and_(not_(_system()), ~exists().where(User.id == AuditEvent.actor_id))


def _conditions(viewer: User, filters: AuditFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if viewer.role != "super_admin":
        for category in SUPER_ADMIN_ONLY_CATEGORIES:
            conditions.append(not_(category_condition(category)))
    if filters.search:
        conditions.append(_matching_people(filters.search))
    if filters.role is not None:
        conditions.append(_role_condition(filters.role))
    if filters.category is not None:
        if viewer.role != "super_admin" and filters.category in SUPER_ADMIN_ONLY_CATEGORIES:
            raise AppError(403, "super_admin_only", "Only the Super Admin can do this.")
        conditions.append(category_condition(filters.category))
    if filters.occurred_from is not None:
        conditions.append(AuditEvent.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        conditions.append(AuditEvent.occurred_at <= filters.occurred_to)
    return conditions


# Entries


def _name(first: str | None, last: str | None) -> str | None:
    return " ".join(part for part in (first, last) if part) or None


def _role(user: User | None, event: AuditEvent) -> str:
    if user is None:
        return "system" if event.actor_id is None and event.ip_address is None else "anonymous"
    if user.role == "client" and user.date_of_birth is not None:
        return "client" if is_adult(user.date_of_birth, user.state) else "teen"
    return user.role if user.role in ROLE_LABELS else "client"


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _entries(db: Session, events: list[AuditEvent]) -> list[AuditEntryOut]:
    """The rows as the screen shows them, with the people they name looked up in bulk."""
    user_ids = {event.actor_id for event in events if event.actor_id is not None}
    user_ids |= {
        target
        for event in events
        if event.target_type == "user" and (target := _as_uuid(event.target_id)) is not None
    }
    invite_ids = {
        target
        for event in events
        if event.target_type == "admin_invitation"
        and (target := _as_uuid(event.target_id)) is not None
    }
    users = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    invites = (
        {
            invite.id: invite
            for invite in db.scalars(
                select(AdminInvitation).where(AdminInvitation.id.in_(invite_ids))
            )
        }
        if invite_ids
        else {}
    )
    entries = []
    for event in events:
        actor = users.get(event.actor_id) if event.actor_id is not None else None
        role = _role(actor, event)
        target_name = None
        target_id = _as_uuid(event.target_id)
        if event.target_type == "user" and target_id in users:
            target = users[target_id]
            target_name = _name(target.first_name, target.last_name)
        elif event.target_type == "admin_invitation" and target_id in invites:
            invite = invites[target_id]
            target_name = _name(invite.first_name, invite.last_name)
        category = category_of(event.action)
        sign_in = category == "sign_in_security"
        reason = None
        if event.action.endswith(_REASON_SUFFIXES):
            value = (event.details or {}).get("reason")
            reason = value if isinstance(value, str) else None
        entries.append(
            AuditEntryOut(
                id=event.id,
                occurred_at=event.occurred_at,
                action=event.action,
                action_label=label_of(event.action),
                category=category,
                category_label=CATEGORY_LABELS[category],
                actor=AuditActor(
                    id=actor.id if actor else None,
                    name=_name(actor.first_name, actor.last_name) if actor else None,
                    email=actor.email if actor else None,
                    role=role,
                    role_label=ROLE_LABELS[role],
                ),
                target=AuditTarget(type=event.target_type, id=event.target_id, name=target_name),
                ip_address=event.ip_address if sign_in else None,
                device=event.user_agent if sign_in else None,
                reason=reason,
            )
        )
    return entries


def _ordered(conditions: list[ColumnElement[bool]]):
    return (
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    )


def search(db: Session, viewer: User, filters: AuditSearch) -> AuditPage:
    """10.1's Audit Log screen, a page at a time (`limit`, `offset`)."""
    stmt = _ordered(_conditions(viewer, filters)).limit(filters.limit + 1).offset(filters.offset)
    events = list(db.scalars(stmt))
    more = len(events) > filters.limit
    items = _entries(db, events[: filters.limit])
    return AuditPage(items=items, has_more=more, message=None if items else NO_RESULTS)


# Export

CSV_HEADER = [
    "Date and time (UTC)",
    "Who",
    "Email",
    "Role",
    "Action",
    "Category",
    "Affected",
    "Affected type",
    "Affected id",
    "IP address",
    "Device",
    "Reason",
]


def _cell(value: object) -> str:
    """A CSV cell that a spreadsheet won't run as a formula (names come from sign-up forms)."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def _row(entry: AuditEntryOut) -> list[str]:
    return [
        _cell(value)
        for value in (
            entry.occurred_at.astimezone(UTC).isoformat(timespec="seconds"),
            entry.actor.name,
            entry.actor.email,
            entry.actor.role_label,
            entry.action_label,
            entry.category_label,
            entry.target.name,
            entry.target.type,
            entry.target.id,
            entry.ip_address,
            entry.device,
            entry.reason,
        )
    ]


def export(db: Session, viewer: User, filters: AuditFilters, request: Request) -> str:
    """10.1's Export: the filtered entries as CSV. The export itself is recorded. Above
    settings.audit_export_max_rows the admin is asked for a shorter date range."""
    conditions = _conditions(viewer, filters)
    try:
        count = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
        if count > settings.audit_export_max_rows:
            raise AppError(422, "export_too_large", EXPORT_TOO_LARGE)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_HEADER)
        # At most audit_export_max_rows, so they're read at once; the people they name are
        # looked up a batch at a time.
        events = list(db.scalars(_ordered(conditions)))
        for start in range(0, len(events), _BATCH):
            for entry in _entries(db, events[start : start + _BATCH]):
                writer.writerow(_row(entry))
        written = len(events)
        audit.record(
            db,
            "audit.exported",
            actor_id=viewer.id,
            request=request,
            # The filters, but not the search text: it can be a Client's name or email.
            details={
                "rows": written,
                "category": filters.category,
                "role": filters.role,
                "from": filters.occurred_from.isoformat() if filters.occurred_from else None,
                "to": filters.occurred_to.isoformat() if filters.occurred_to else None,
                "search": filters.search is not None,
            },
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "export_failed", EXPORT_FAILED) from None
    return buffer.getvalue()


def export_filename() -> str:
    return f"audit-log-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
