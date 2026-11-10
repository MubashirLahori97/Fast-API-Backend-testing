"""Escalation Management (Super Admin and Admin story 4.1).

The listing is built here, with 4.1's search and filters, over the conversations package's
`escalations` (safety.list_escalations has only the status and level filters). Changing the
review status goes through `safety.set_review_status`. Every view of the details, note and
status change is audited; loading the listing isn't (as in Support Requests).

Escalation rows keep plain ids, so the account, profile and messages are outer-joined: once
they're deleted, the row still shows its level, status and time.
"""

import uuid
from datetime import date

from fastapi import Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.admin.common import day_range, like
from app.admin.escalations.models import EscalationNote
from app.admin.escalations.schemas import (
    ClientRef,
    EscalationDetail,
    EscalationPage,
    EscalationProfile,
    EscalationRow,
    ProfileType,
    ReviewerRef,
    ReviewOut,
    ReviewStatus,
)
from app.auth.models import User
from app.conversations import safety
from app.conversations.models import Escalation, Message
from app.conversations.schemas import EscalationLevel
from app.core import audit
from app.core.errors import AppError, database_errors_retryable
from app.profiles.models import Profile
from app.teens import service as teens

# Super Admin and Admin 4.1's messages.
NO_ESCALATIONS = "There are no escalations to review."
NO_RESPONSE = "No response"
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
MARKED_NOT_REVIEWED = "This escalation has been marked as not yet reviewed."
NOTE_SAVED = "Your note has been saved."  # Super Admin 5.1's wording
NOTES_UNAVAILABLE = "This client’s account has been deleted, so notes can’t be added."


def _query():
    trigger = aliased(Message)
    return (
        select(Escalation, User, Profile, trigger.safety_reason)
        .outerjoin(User, User.id == Escalation.account_id)
        .outerjoin(Profile, Profile.id == Escalation.profile_id)
        .outerjoin(trigger, trigger.id == Escalation.message_id)
    )


def _row_fields(
    escalation: Escalation, account: User | None, profile: Profile | None, reason: str | None
) -> dict:
    # The client's own profile, or a teen's own (their account is the teen's): the name is on the
    # account. A family member's is on the profile, with the advocate's beside it.
    if escalation.profile_type in ("self", "teen"):
        first_name = account.first_name if account else None
    else:
        first_name = profile.first_name if profile else None
    return {
        "id": escalation.id,
        "level": escalation.level,
        "status": escalation.status,
        "client": (
            ClientRef(id=account.id, first_name=account.first_name, email=account.email)
            if account
            else None
        ),
        "profile": EscalationProfile(
            id=escalation.profile_id,
            type=escalation.profile_type,
            first_name=first_name,
            advocate_first_name=(
                account.first_name
                if escalation.profile_type == "family_member" and account
                else None
            ),
        ),
        "reason": reason,
        "detected_at": escalation.detected_at,
    }


def list_escalations(
    db: Session,
    *,
    search: str | None = None,
    level: EscalationLevel | None = None,
    status: ReviewStatus | None = None,
    profile_type: ProfileType | None = None,
    detected_from: date | None = None,
    detected_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> EscalationPage:
    """4.1's listing: Not yet reviewed first, newest first. Search by the client's first name
    or email; filter by level, status, profile type and date range."""
    query = _query()
    if search and search.strip():
        pattern = like(search.strip())
        query = query.where(
            or_(User.first_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    if level is not None:
        query = query.where(Escalation.level == level)
    if status is not None:
        query = query.where(Escalation.status == status)
    if profile_type is not None:
        query = query.where(Escalation.profile_type == profile_type)
    start, end = day_range(detected_from, detected_to)
    if start is not None:
        query = query.where(Escalation.detected_at >= start)
    if end is not None:
        query = query.where(Escalation.detected_at < end)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(
            case((Escalation.status == "not_reviewed", 0), else_=1),
            Escalation.detected_at.desc(),
            Escalation.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    items = [EscalationRow(**_row_fields(*row)) for row in rows]
    return EscalationPage(items=items, total=total, message=None if items else NO_ESCALATIONS)


def _reviewer(db: Session, escalation: Escalation) -> ReviewerRef | None:
    if escalation.reviewed_by_id is None:
        return None
    reviewer = db.get(User, escalation.reviewed_by_id)
    return ReviewerRef(
        id=escalation.reviewed_by_id, first_name=reviewer.first_name if reviewer else None
    )


def _detail(db: Session, escalation_id: uuid.UUID) -> EscalationDetail:
    query = _query()
    row = db.execute(query.where(Escalation.id == escalation_id)).first()
    if row is None:
        raise AppError(404, "escalation_not_found", safety.ESCALATION_NOT_FOUND)
    escalation = row[0]
    trigger = db.get(Message, escalation.message_id)
    shown = db.get(Message, escalation.response_message_id)
    note = db.get(EscalationNote, escalation.id)
    asks_option = escalation.level in safety.HOLD_LEVELS
    choice = escalation.client_choice
    return EscalationDetail(
        **_row_fields(*row),
        conversation_id=escalation.conversation_id,
        triggering_message=trigger.text if trigger else None,
        oracle_showed=shown.text if shown else None,
        outside_us=escalation.outside_us,
        poison_control=escalation.poison_control,
        client_choice=choice,
        client_choice_label=(
            safety.OPTION_LABELS[choice] if choice else NO_RESPONSE if asks_option else None
        ),
        chosen_at=escalation.chosen_at,
        # Teens with their own account: when the parent was told (story 3.2).
        parent_told_at=(
            teens.parent_told_at(db, escalation.id) if escalation.profile_type == "teen" else None
        ),
        review_notes=note.notes if note else None,
        reviewed_by=_reviewer(db, escalation),
        reviewed_at=escalation.reviewed_at,
    )


def _audit(db: Session, action: str, escalation_id: uuid.UUID, admin: User, request) -> None:
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="escalation",
        target_id=escalation_id,
        request=request,
    )


def get_escalation(
    db: Session, admin: User, escalation_id: uuid.UUID, request: Request | None = None
) -> EscalationDetail:
    """4.1's details. Every view is audited."""
    detail = _detail(db, escalation_id)
    with database_errors_retryable(db):
        _audit(db, "escalation.viewed", escalation_id, admin, request)
        db.commit()
    return detail


def _set_notes(db: Session, admin: User, escalation: Escalation, notes: str | None) -> None:
    note = db.get(EscalationNote, escalation.id, with_for_update=True)
    if notes is None:
        if note is not None:
            db.delete(note)
        return
    if note is None:
        db.add(
            EscalationNote(
                escalation_id=escalation.id,
                account_id=escalation.account_id,
                notes=notes,
                updated_by_id=admin.id,
            )
        )
    else:
        note.notes = notes
        note.updated_by_id = admin.id


def _load(db: Session, escalation_id: uuid.UUID) -> Escalation:
    escalation = db.get(Escalation, escalation_id)
    if escalation is None:
        raise AppError(404, "escalation_not_found", safety.ESCALATION_NOT_FOUND)
    return escalation


def _check_account(db: Session, escalation: Escalation) -> None:
    """Notes are deleted with the client's account, so none can be kept once it's gone."""
    if db.get(User, escalation.account_id) is None:
        raise AppError(409, "account_deleted", NOTES_UNAVAILABLE, "notes")


def save_notes(
    db: Session,
    admin: User,
    escalation_id: uuid.UUID,
    notes: str | None,
    request: Request | None = None,
) -> str:
    """Replaces the review notes (empty clears them). Audited without the text."""
    with database_errors_retryable(db):
        escalation = _load(db, escalation_id)
        _check_account(db, escalation)
        _set_notes(db, admin, escalation, notes)
        _audit(db, "escalation.note_saved", escalation.id, admin, request)
        db.commit()
    return NOTE_SAVED


def set_status(
    db: Session,
    admin: User,
    escalation_id: uuid.UUID,
    status: ReviewStatus,
    notes: str | None,
    notes_sent: bool,
    request: Request | None = None,
) -> ReviewOut:
    """Mark as reviewed (who and when are recorded) or Not yet reviewed again, which moves it
    back to the top of the list. Any notes sent are saved in the same transaction."""
    with database_errors_retryable(db):
        escalation = _load(db, escalation_id)
        if notes_sent:
            _check_account(db, escalation)
            _set_notes(db, admin, escalation, notes)
            _audit(db, "escalation.note_saved", escalation.id, admin, request)
        # Commits, with the notes, when the status changes.
        safety.set_review_status(db, escalation.id, status, admin.id, request)
        db.commit()  # when it didn't change, the notes still need saving
    message = safety.MARKED_AS_REVIEWED if status == "reviewed" else MARKED_NOT_REVIEWED
    return ReviewOut(escalation=_detail(db, escalation_id), message=message)
