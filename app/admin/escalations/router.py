import uuid
from datetime import date

from fastapi import APIRouter, Request

from app.admin.common import NOTE_SAVED, Limit, Offset
from app.admin.dependencies import AdminSession
from app.admin.escalations import service
from app.admin.escalations.schemas import (
    EscalationDetail,
    EscalationPage,
    NotesBody,
    ProfileType,
    ReviewBody,
    ReviewOut,
    ReviewStatus,
)
from app.conversations.schemas import EscalationLevel
from app.core.database import DbSession
from app.core.schemas import MessageResponse

router = APIRouter(prefix="/admin/escalations", tags=["admin: escalations"])


@router.get("")
def list_escalations(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    level: EscalationLevel | None = None,
    status: ReviewStatus | None = None,
    profile_type: ProfileType | None = None,
    detected_from: date | None = None,
    detected_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> EscalationPage:
    """Super Admin and Admin 4.1: each escalation's level, status, profile, reason and time, Not
    yet reviewed first, newest first. Search by the client's first name or email."""
    return service.list_escalations(
        db,
        search=search,
        level=level,
        status=status,
        profile_type=profile_type,
        detected_from=detected_from,
        detected_to=detected_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{escalation_id}")
def get_escalation(
    escalation_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> EscalationDetail:
    """4.1's details: the triggering message only, the Oracle's reason, what it showed, what
    the client chose ("No response" when nothing), and the review notes. Audited."""
    return service.get_escalation(db, session.user, escalation_id, request)


@router.put("/{escalation_id}/notes")
def save_notes(
    escalation_id: uuid.UUID,
    body: NotesBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> MessageResponse:
    """The reviewer's notes, replaced as a whole (empty clears them)."""
    service.save_notes(db, session.user, escalation_id, body.notes, request)
    return MessageResponse(message=NOTE_SAVED)


@router.post("/{escalation_id}/review")
def set_review_status(
    escalation_id: uuid.UUID,
    body: ReviewBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> ReviewOut:
    """Mark as reviewed ("reviewed", with any notes) or Not yet reviewed again
    ("not_reviewed"). The reviewer and time are recorded."""
    return service.set_status(
        db,
        session.user,
        escalation_id,
        body.status,
        body.notes,
        "notes" in body.model_fields_set,
        request,
    )
