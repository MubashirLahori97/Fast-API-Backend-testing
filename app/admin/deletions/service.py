"""Data Deletion Requests (Super Admin and Admin story 5.2, 6 Nov 19:22).

- The listing and details read the privacy package's `deletion_requests`, outer-joined to the
  account and profile (both can be gone after the purge). Every view of the details is audited.
- The review checklist, notes and legal hold note are kept in `deletion_request_reviews`.
- Starting the review, completing (after the grace period and the checklist), the legal hold
  and declining are the privacy package's functions; its purge job deletes the data and emails
  the client and any teen affected. The grace period ends without anyone acting (the privacy
  sweep), which is when the team is notified.
- A Teen Deletion for a teen who can't sign in is created here, from the email's date: no grace
  period, straight to Pending review, due 45 calendar days from that date.
- The admin sweep reminds the team once when an open request is 5 days from its deadline
  (Super Admin 11.1), except while it's on legal hold.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.accounts.models import OPEN_DELETION_STATUSES, DeletionRequest
from app.admin.common import day_range, day_start, format_date, like
from app.admin.deletions.models import DeletionReview
from app.admin.deletions.schemas import (
    AffectedProfile,
    AffectedTeen,
    Checklist,
    ClientRef,
    DeletionCreated,
    DeletionDetail,
    DeletionKind,
    DeletionPage,
    DeletionRow,
    DeletionSource,
    DeletionStatus,
    PersonRef,
    ProfileRef,
    WhatWillBeDeleted,
)
from app.admin.notifications.service import notify_admins
from app.auth.models import User
from app.core import audit
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import AppError, database_errors_retryable
from app.notifications import service as notifications
from app.privacy import emails as privacy_emails
from app.privacy import service as privacy
from app.privacy import teens as privacy_teens
from app.profiles.models import Profile
from app.support.service import account_type

# Super Admin and Admin 5.2's messages.
NO_REQUESTS = "There are no deletion requests right now."
CREATED = "The deletion request has been created. It’s due by {date}."
COMPLETE_CONFIRMATION = "Permanently delete this data? This can’t be undone."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
CHECKLIST_SAVED = "The review checklist has been saved."
NOT_A_TEEN = "Only a teen’s own account can be chosen here."
ALREADY_OPEN = "This account already has an open deletion request."
CLIENT_NOT_FOUND = "We couldn’t find that client."
IDENTITY_IN_APP = "The request came from the signed-in account holder."
IDENTITY_BY_EMAIL = "The email came from the address registered to the account."


def _now() -> datetime:
    return datetime.now(UTC)


def _is_open():
    return DeletionRequest.status.in_(OPEN_DELETION_STATUSES)


def days_left(now: datetime, due: datetime) -> int:
    """Calendar days until the deadline (5.2's "days remaining"), rounded up, so a request due
    later today has 1; negative once it's overdue."""
    return math.ceil((due - now) / timedelta(days=1))


def _near_deadline(deletion: DeletionRequest, now: datetime) -> bool:
    return (
        deletion.status in OPEN_DELETION_STATUSES
        and deletion.status != "on_legal_hold"
        and deletion.due_at <= now + timedelta(days=settings.deletion_highlight_days)
    )


def _query():
    return (
        select(DeletionRequest, User, Profile)
        .outerjoin(User, User.id == DeletionRequest.account_id)
        .outerjoin(Profile, Profile.id == DeletionRequest.profile_id)
    )


def _row_fields(
    deletion: DeletionRequest, account: User | None, profile: Profile | None, now: datetime
) -> dict:
    if profile is not None and profile.account_id != deletion.account_id:
        profile = None
    return {
        "id": deletion.id,
        "kind": deletion.kind,
        "source": deletion.source,
        "status": deletion.status,
        "client": (
            ClientRef(
                id=account.id,
                first_name=account.first_name,
                email=account.email,
                account_type=account_type(account),
            )
            if account is not None
            else None
        ),
        "profile": (
            ProfileRef(
                id=profile.id,
                first_name=account.first_name
                if profile.is_self and account
                else profile.first_name,
                is_self=profile.is_self,
            )
            if profile is not None
            else None
        ),
        "received_at": deletion.requested_at,
        "grace_ends_at": deletion.grace_ends_at,
        "due_at": deletion.due_at,
        "days_left": days_left(now, deletion.due_at),
        "highlighted": _near_deadline(deletion, now),
    }


def list_requests(
    db: Session,
    *,
    search: str | None = None,
    kind: DeletionKind | None = None,
    source: DeletionSource | None = None,
    status: DeletionStatus | None = None,
    received_from=None,
    received_to=None,
    limit: int = 50,
    offset: int = 0,
) -> DeletionPage:
    """5.2's listing: open requests first, closest deadline first, then closed ones, newest
    first. Search by the client's first name or email; filter by type, source, status and date
    received."""
    query = _query()
    if search and search.strip():
        pattern = like(search.strip())
        query = query.where(
            or_(User.first_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    if kind is not None:
        query = query.where(DeletionRequest.kind == kind)
    if source is not None:
        query = query.where(DeletionRequest.source == source)
    if status is not None:
        query = query.where(DeletionRequest.status == status)
    start, end = day_range(received_from, received_to)
    if start is not None:
        query = query.where(DeletionRequest.requested_at >= start)
    if end is not None:
        query = query.where(DeletionRequest.requested_at < end)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(
            case((_is_open(), 0), else_=1),
            case((_is_open(), DeletionRequest.due_at)),
            DeletionRequest.requested_at.desc(),
            DeletionRequest.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    now = _now()
    items = [DeletionRow(**_row_fields(*row, now)) for row in rows]
    return DeletionPage(items=items, total=total, message=None if items else NO_REQUESTS)


def _family(db: Session, account_id: uuid.UUID) -> list[Profile]:
    return list(
        db.scalars(
            select(Profile)
            .where(Profile.account_id == account_id, Profile.intake_completed_at.is_not(None))
            .order_by(Profile.is_self.desc(), Profile.created_at)
        )
    )


def _affected(db: Session, deletion: DeletionRequest, account: User | None) -> WhatWillBeDeleted:
    """What will be deleted: the profiles and data affected, including any invited teens (none
    once purged)."""

    def out(profile: Profile, owner: User | None) -> AffectedProfile:
        name = owner.first_name if profile.is_self and owner else profile.first_name
        return AffectedProfile(id=profile.id, first_name=name, is_self=profile.is_self)

    if deletion.kind == "family_member":
        profile = db.get(Profile, deletion.profile_id) if deletion.profile_id else None
        profiles = (
            [out(profile, account)]
            if profile is not None and profile.account_id == deletion.account_id
            else []
        )
        return WhatWillBeDeleted(account_deleted=False, profiles=profiles, subscription_kept=True)
    profiles = [out(p, account) for p in _family(db, deletion.account_id)] if account else []
    invited: list[AffectedTeen] = []
    if deletion.kind == "account" and account is not None:
        for teen_id in privacy_teens.invited_teen_accounts(db, account.id):
            teen = db.get(User, teen_id)
            if teen is not None:
                invited.append(AffectedTeen(account_id=teen.id, first_name=teen.first_name))
    return WhatWillBeDeleted(
        account_deleted=True, profiles=profiles, invited_teens=invited, subscription_kept=False
    )


def _person(db: Session, user_id: uuid.UUID | None) -> PersonRef | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return PersonRef(id=user_id, first_name=user.first_name if user else None)


def _detail(db: Session, deletion_id: uuid.UUID) -> DeletionDetail:
    row = db.execute(_query().where(DeletionRequest.id == deletion_id)).first()
    if row is None:
        raise AppError(404, "deletion_request_not_found", privacy.REQUEST_NOT_FOUND)
    deletion, account, _profile = row
    review = db.get(DeletionReview, deletion.id)
    by_email = deletion.source == "by_email"
    return DeletionDetail(
        **_row_fields(*row, _now()),
        what_will_be_deleted=_affected(db, deletion, account),
        checklist=Checklist(
            # In-app requests come from the signed-in account holder (5.2's identity check).
            identity_confirmed=review.identity_confirmed if review else not by_email,
            legal_hold_checked=review.legal_hold_checked if review else False,
            identity_check=IDENTITY_BY_EMAIL if by_email else IDENTITY_IN_APP,
        ),
        internal_notes=review.internal_notes if review else None,
        legal_hold_note=review.legal_hold_note if review else None,
        legal_hold_at=deletion.legal_hold_at,
        email_received_on=review.email_received_on if review else None,
        created_by=_person(db, deletion.created_by_id),
        completed_by=_person(db, deletion.completed_by_id),
        completed_at=deletion.completed_at,
        purged_at=deletion.purged_at,
        complete_confirmation=COMPLETE_CONFIRMATION,
        grace_period_message=(
            privacy.grace_message(deletion) if deletion.status == "grace_period" else None
        ),
    )


def _audit(db: Session, action: str, deletion_id: uuid.UUID, admin: User, request, **details):
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="deletion_request",
        target_id=deletion_id,
        request=request,
        details=details or None,
    )


def get_request(
    db: Session, admin: User, deletion_id: uuid.UUID, request: Request | None = None
) -> DeletionDetail:
    detail = _detail(db, deletion_id)
    with database_errors_retryable(db):
        _audit(db, "deletion.viewed", deletion_id, admin, request)
        db.commit()
    return detail


def _review(db: Session, deletion: DeletionRequest) -> DeletionReview:
    """The request's review row, created if needed, locked."""
    db.execute(
        insert(DeletionReview)
        .values(
            deletion_request_id=deletion.id,
            identity_confirmed=deletion.source == "in_app",
        )
        .on_conflict_do_nothing(index_elements=["deletion_request_id"])
    )
    return db.get(DeletionReview, deletion.id, with_for_update=True, populate_existing=True)


def _load(db: Session, deletion_id: uuid.UUID) -> DeletionRequest:
    deletion = db.get(DeletionRequest, deletion_id)
    if deletion is None:
        raise AppError(404, "deletion_request_not_found", privacy.REQUEST_NOT_FOUND)
    return deletion


def save_notes(
    db: Session, admin: User, deletion_id: uuid.UUID, notes: str | None, request=None
) -> None:
    with database_errors_retryable(db):
        review = _review(db, _load(db, deletion_id))
        review.internal_notes = notes
        review.updated_by_id = admin.id
        _audit(db, "deletion.note_saved", deletion_id, admin, request)
        db.commit()


def save_checklist(
    db: Session,
    admin: User,
    deletion_id: uuid.UUID,
    identity_confirmed: bool,
    legal_hold_checked: bool,
    request=None,
) -> None:
    with database_errors_retryable(db):
        review = _review(db, _load(db, deletion_id))
        changed = (review.identity_confirmed, review.legal_hold_checked) != (
            identity_confirmed,
            legal_hold_checked,
        )
        review.identity_confirmed = identity_confirmed
        review.legal_hold_checked = legal_hold_checked
        review.updated_by_id = admin.id
        if changed:
            _audit(
                db,
                "deletion.checklist_saved",
                deletion_id,
                admin,
                request,
                identity_confirmed=identity_confirmed,
                legal_hold_checked=legal_hold_checked,
            )
        db.commit()


def complete(
    db: Session,
    admin: User,
    deletion_id: uuid.UUID,
    identity_confirmed: bool,
    legal_hold_checked: bool,
    request=None,
) -> str:
    """Complete deletion: the checklist is saved first, then the privacy package refuses a
    request still in its grace period, an incomplete checklist or a legal hold, and otherwise
    marks it completed for the purge."""
    save_checklist(db, admin, deletion_id, identity_confirmed, legal_hold_checked, request)
    return privacy.complete_request(
        db,
        admin,
        deletion_id,
        identity_confirmed=identity_confirmed,
        legal_hold_checked=legal_hold_checked,
        request=request,
    )


def place_legal_hold(
    db: Session,
    admin: User,
    deletion_id: uuid.UUID,
    note: str | None,
    send: SendEmail,
    request=None,
) -> str:
    """Place on legal hold, with the team's note: the deletion waits and the client is
    emailed."""
    with database_errors_retryable(db):
        review = _review(db, _load(db, deletion_id))
        if note is not None:
            review.legal_hold_note = note
            review.updated_by_id = admin.id
        db.commit()
    return privacy.place_legal_hold(db, admin, deletion_id, send, request)


def create_teen_request(
    db: Session,
    admin: User,
    teen_account_id: uuid.UUID,
    email_received_on,
    note: str | None,
    send: SendEmail,
    request: Request | None = None,
) -> DeletionCreated:
    """5.2's + Create deletion request: a Teen Deletion "By email", for a teen who can't sign in
    at all, once the team has checked the email came from the teen's registered address (the
    form's identity check). Requests from anyone else, such as the parent, aren't accepted:
    only a teen's own account can be chosen. Because the teen can't sign in there's no grace
    period: it goes straight to Pending review (locked), due 45 calendar days from the day the
    email was received, and the teen is acknowledged by email."""
    received_at = day_start(email_received_on)
    due_at = received_at + timedelta(days=settings.deletion_due_days)
    with database_errors_retryable(db):
        teen = db.get(User, teen_account_id, with_for_update=True)
        if teen is None or teen.role != "client":
            raise AppError(404, "client_not_found", CLIENT_NOT_FOUND, "teen_account_id")
        if account_type(teen) != "teen":
            raise AppError(422, "not_a_teen_account", NOT_A_TEEN, "teen_account_id")
        if accounts.open_account_deletion(db, teen) is not None:
            raise AppError(409, "deletion_already_requested", ALREADY_OPEN, "teen_account_id")
        now = _now()
        deletion = DeletionRequest(
            account_id=teen.id,
            kind="teen",
            source="by_email",
            status="pending",
            requested_at=received_at,
            grace_ends_at=None,
            locked_at=now,
            due_at=due_at,
            created_by_id=admin.id,
            # Made by the team, so nobody needs to be told about it.
            team_notified_at=now,
        )
        try:
            with db.begin_nested():
                db.add(deletion)
                db.flush()
        except IntegrityError:  # another request for this account was made meanwhile
            raise AppError(
                409, "deletion_already_requested", ALREADY_OPEN, "teen_account_id"
            ) from None
        db.add(
            DeletionReview(
                deletion_request_id=deletion.id,
                identity_confirmed=True,
                email_received_on=email_received_on,
                internal_notes=note,
                updated_by_id=admin.id,
            )
        )
        notifications.cancel_scheduled(db, teen)
        accounts.sign_out_everywhere(db, teen, forget_devices=False)
        _audit(db, "deletion.created_by_team", deletion.id, admin, request, kind="teen")
        _audit(db, "deletion.acknowledged", deletion.id, admin, request, kind="teen")
        teen_email = teen.email
        db.commit()
    send(privacy_emails.by_email_acknowledgement(teen_email, format_date(due_at)))
    return DeletionCreated(
        deletion_request=_detail(db, deletion.id), message=CREATED.format(date=format_date(due_at))
    )


def send_deadline_reminders(db: Session) -> int:
    """Super Admin 11.1: one reminder per open request once it's within 5 days of its 45-day
    deadline (none while on legal hold). Commits. Returns how many were sent."""
    now = _now()
    near_by = now + timedelta(days=settings.deletion_highlight_days)
    reminded = exists().where(
        DeletionReview.deletion_request_id == DeletionRequest.id,
        DeletionReview.deadline_reminded_at.is_not(None),
    )
    ids = db.scalars(
        select(DeletionRequest.id)
        .where(
            _is_open(),
            DeletionRequest.status != "on_legal_hold",
            DeletionRequest.due_at <= near_by,
            ~reminded,
        )
        .order_by(DeletionRequest.due_at)
        .limit(settings.knowledge_gap_batch_size)
    ).all()
    sent = 0
    for deletion_id in ids:
        deletion = db.get(DeletionRequest, deletion_id)
        review = _review(db, deletion)
        if review.deadline_reminded_at is None:
            review.deadline_reminded_at = now
            days = max(0, days_left(now, deletion.due_at))
            notify_admins(db, "deletion_deadline", {"days": days}, target_id=deletion.id)
            sent += 1
        db.commit()
    return sent
