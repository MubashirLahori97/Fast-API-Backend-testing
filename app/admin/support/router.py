import uuid
from datetime import date

from fastapi import APIRouter, Request

from app.admin.common import Limit, Offset
from app.admin.dependencies import AdminSession
from app.admin.support import service
from app.admin.support.schemas import (
    AdminSupportRequestDetail,
    SupportNotesBody,
    SupportRequestList,
)
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse
from app.support import service as support
from app.support.schemas import AccountType, Kind, Status

router = APIRouter(prefix="/admin/support-requests", tags=["admin: support requests"])


@router.get("")
def list_requests(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    kind: Kind | None = None,
    status: Status | None = None,
    account_type: AccountType | None = None,
    received_from: date | None = None,
    received_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> SupportRequestList:
    """Super Admin and Admin 5.1: open requests first, oldest first. Search by the client's
    first name or email; filter by type, status, account type and date received."""
    return service.list_requests(
        db,
        session.user,
        kind=kind,
        status=status,
        account_type=account_type,
        search=search,
        received_from=received_from,
        received_to=received_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{request_id}")
def get_request(
    request_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> AdminSupportRequestDetail:
    """5.1's details: the full message, the profile it's about, the internal notes and who
    resolved it. Audited."""
    return service.get_request(db, session.user, request_id, request)


@router.put("/{request_id}/notes")
def save_notes(
    request_id: uuid.UUID,
    body: SupportNotesBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> MessageResponse:
    return MessageResponse(
        message=support.save_notes(db, session.user, request_id, body.notes, request)
    )


@router.post("/{request_id}/resolve")
def resolve(
    request_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> MessageResponse:
    """Mark as resolved, with who and when."""
    return MessageResponse(message=support.resolve(db, session.user, request_id, request))


@router.post("/{request_id}/reopen")
def reopen(
    request_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> MessageResponse:
    return MessageResponse(message=support.reopen(db, session.user, request_id, request))


@router.post("/{request_id}/change-email")
def change_email(
    request_id: uuid.UUID,
    session: AdminSession,
    request: Request,
    send: EmailLater,
    db: DbSession,
) -> MessageResponse:
    """Super Admin and Admin 3.1: changes the client's email to the address their Email Change
    Request asked for. They're told at both addresses, signed out everywhere, their trusted
    devices are cleared, and the request is resolved."""
    return MessageResponse(
        message=service.change_email(db, session.user, request_id, send, request)
    )
