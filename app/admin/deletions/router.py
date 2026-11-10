import uuid
from datetime import date

from fastapi import APIRouter, Request

from app.admin.common import NOTE_SAVED, Limit, Offset
from app.admin.deletions import service
from app.admin.deletions.schemas import (
    ChecklistBody,
    CreateTeenDeletionBody,
    DeletionCreated,
    DeletionDetail,
    DeletionKind,
    DeletionPage,
    DeletionSource,
    DeletionStatus,
    LegalHoldBody,
    NotesBody,
)
from app.admin.dependencies import AdminSession
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse
from app.privacy import service as privacy

router = APIRouter(prefix="/admin/deletion-requests", tags=["admin: deletion requests"])


@router.get("")
def list_requests(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    kind: DeletionKind | None = None,
    source: DeletionSource | None = None,
    status: DeletionStatus | None = None,
    received_from: date | None = None,
    received_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> DeletionPage:
    """Super Admin and Admin 5.2: each request's type, source, status, client, profile, date
    received, grace period end and deletion due date (days left, highlighted within 5 days),
    closest deadline first."""
    return service.list_requests(
        db,
        search=search,
        kind=kind,
        source=source,
        status=status,
        received_from=received_from,
        received_to=received_to,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=201)
def create_teen_request(
    body: CreateTeenDeletionBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> DeletionCreated:
    """5.2's + Create deletion request: a Teen Deletion by email, for a teen who can't sign
    in at all and wrote from their registered address. No grace period: it goes straight to
    Pending review, due 45 calendar days from the email, and the teen is acknowledged by
    email."""
    return service.create_teen_request(
        db, session.user, body.teen_account_id, body.email_received_on, body.note, send, request
    )


@router.get("/{deletion_id}")
def get_request(
    deletion_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> DeletionDetail:
    """5.2's details: what will be deleted, the review checklist and the notes. Audited."""
    return service.get_request(db, session.user, deletion_id, request)


@router.put("/{deletion_id}/notes")
def save_notes(
    deletion_id: uuid.UUID,
    body: NotesBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> MessageResponse:
    service.save_notes(db, session.user, deletion_id, body.notes, request)
    return MessageResponse(message=NOTE_SAVED)


@router.put("/{deletion_id}/checklist")
def save_checklist(
    deletion_id: uuid.UUID,
    body: ChecklistBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> MessageResponse:
    """The review checklist's ticks: identity confirmed, legal hold checked."""
    service.save_checklist(
        db, session.user, deletion_id, body.identity_confirmed, body.legal_hold_checked, request
    )
    return MessageResponse(message=service.CHECKLIST_SAVED)


@router.post("/{deletion_id}/start-review")
def start_review(
    deletion_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> MessageResponse:
    """Pending review to In progress. Not during the grace period."""
    return MessageResponse(message=privacy.start_review(db, session.user, deletion_id, request))


@router.post("/{deletion_id}/complete")
def complete(
    deletion_id: uuid.UUID,
    body: ChecklistBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> MessageResponse:
    """Complete deletion, once the grace period has ended ("This request can be completed
    after the grace period ends on [date]." otherwise) and the checklist is complete ("Please
    complete the review checklist first."). The purge deletes only what the type covers, then
    emails the client and any teen affected."""
    message = service.complete(
        db, session.user, deletion_id, body.identity_confirmed, body.legal_hold_checked, request
    )
    return MessageResponse(message=message)


@router.post("/{deletion_id}/legal-hold")
def place_legal_hold(
    deletion_id: uuid.UUID,
    body: LegalHoldBody,
    session: AdminSession,
    request: Request,
    send: EmailLater,
    db: DbSession,
) -> MessageResponse:
    """Place on legal hold, with a note: the deletion waits, and the client is told by email."""
    message = service.place_legal_hold(db, session.user, deletion_id, body.note, send, request)
    return MessageResponse(message=message)


@router.post("/{deletion_id}/lift-legal-hold")
def lift_legal_hold(
    deletion_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> MessageResponse:
    """The hold is lifted, and the deletion continues as usual."""
    return MessageResponse(message=privacy.lift_legal_hold(db, session.user, deletion_id, request))


@router.post("/{deletion_id}/decline")
def decline(
    deletion_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> MessageResponse:
    """Turns the request down: the profile or account is back in use as it was."""
    return MessageResponse(message=privacy.decline_request(db, session.user, deletion_id, request))
