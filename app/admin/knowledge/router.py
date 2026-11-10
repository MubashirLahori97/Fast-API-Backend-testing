import uuid
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Request, Response, UploadFile

from app.admin.common import Limit, Offset
from app.admin.dependencies import AdminSession
from app.admin.knowledge import service
from app.admin.knowledge.schemas import (
    ContentDetail,
    ContentEdit,
    ContentNew,
    ContentPage,
    ContentSaved,
    ContentStatus,
    ContentType,
    DismissBody,
    FileOut,
    GapActionOut,
    GapDetail,
    GapPage,
    GapStatus,
    KnowledgeScreen,
    RejectBody,
    RollbackBody,
    VersionDetail,
)
from app.core.database import DbSession
from app.oracle.dependencies import OracleService

router = APIRouter(prefix="/admin/knowledge", tags=["admin: knowledge base"])


@router.get("")
def knowledge_screen(session: AdminSession, db: DbSession) -> KnowledgeScreen:
    """6.1's Knowledge Base screen: the number of new knowledge gaps, and content waiting for
    approval. No Content Sources (6 Nov 19:22)."""
    return service.screen(db)


@router.get("/contents")
def list_contents(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    content_type: ContentType | None = None,
    status: ContentStatus | None = None,
    updated_from: date | None = None,
    updated_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ContentPage:
    """6.1's content listing: Pending approval first, then newest first. Search by title or
    words in the content."""
    return service.list_contents(
        db,
        search=search,
        content_type=content_type,
        status=status,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=limit,
        offset=offset,
    )


@router.post("/contents", status_code=201)
def create_content(
    body: ContentNew,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    """6.2's Add Content (or 6.3's Add answer, with knowledge_gap_id): action "draft" saves a
    draft; "publish" publishes (Super Admin only, 403 for Admins); "send_for_approval" sends an
    Admin's for approval (and makes a New gap Answer pending)."""
    return service.create_content(db, session.user, body, oracle, request)


@router.get("/contents/{content_id}")
def get_content(content_id: uuid.UUID, session: AdminSession, db: DbSession) -> ContentDetail:
    """6.1's details: the latest version to read, the linked gap, the version history and, for
    a rejected item, the Super Admin's reason."""
    return service.get_content(db, session.user, content_id)


@router.put("/contents/{content_id}")
def edit_content(
    content_id: uuid.UUID,
    body: ContentEdit,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    """6.1's Edit: a new version, published straight away for the Super Admin's Publish, or
    Pending approval for an Admin's Send for approval."""
    return service.edit_content(db, session.user, content_id, body, oracle, request)


@router.get("/contents/{content_id}/versions/{number}")
def get_version(
    content_id: uuid.UUID, number: int, session: AdminSession, db: DbSession
) -> VersionDetail:
    """One version from the history, read-only."""
    return service.get_version(db, content_id, number)


@router.post("/contents/{content_id}/approve")
def approve(
    content_id: uuid.UUID,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    """Approve & publish the version waiting for approval. Super Admin only (403 for Admins).
    The Admin who sent it is notified."""
    return service.approve(db, session.user, content_id, oracle, request)


@router.post("/contents/{content_id}/reject")
def reject(
    content_id: uuid.UUID,
    body: RejectBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> ContentSaved:
    """Reject the version waiting for approval, with a reason. Super Admin only. It stays in
    the listing as Rejected; a gap it answered goes back to New; the Admin who sent it is
    notified."""
    return service.reject(db, session.user, content_id, body.reason, request)


@router.post("/contents/{content_id}/archive")
def archive(
    content_id: uuid.UUID,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    return service.archive(db, session.user, content_id, oracle, request)


@router.post("/contents/{content_id}/restore")
def restore(
    content_id: uuid.UUID,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    return service.restore(db, session.user, content_id, oracle, request)


@router.post("/contents/{content_id}/roll-back")
def roll_back(
    content_id: uuid.UUID,
    body: RollbackBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
    oracle: OracleService,
) -> ContentSaved:
    """Publishes an earlier version again (an Admin: only one that was published before)."""
    return service.roll_back(db, session.user, content_id, body.version, oracle, request)


@router.post("/files", status_code=201)
def upload_file(
    session: AdminSession,
    request: Request,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> FileOut:
    """6.2's upload: a PDF, Word (DOCX) or text file, up to the size limit. Use the returned id
    as the content's file_id."""
    return service.upload_file(db, session.user, file, request)


@router.get("/files/{file_id}")
def download_file(file_id: uuid.UUID, session: AdminSession, db: DbSession) -> Response:
    file = service.file_for_download(db, file_id)
    return Response(
        content=file.data,
        media_type=file.media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name)}"},
    )


@router.get("/gaps")
def list_gaps(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    topic: str | None = None,
    status: GapStatus | None = None,
    asked_from: date | None = None,
    asked_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> GapPage:
    """6.3's Knowledge Gaps: New first, most asked first. Status New, Answer pending, Answered or
    Dismissed. Only the question: never the client's name, email or conversation."""
    return service.list_gaps(
        db,
        search=search,
        topic=topic,
        status=status,
        asked_from=asked_from,
        asked_to=asked_to,
        limit=limit,
        offset=offset,
    )


@router.get("/gaps/{gap_id}")
def get_gap(gap_id: uuid.UUID, session: AdminSession, db: DbSession) -> GapDetail:
    """A gap, with its answer and the Add answer form's prefill."""
    return service.get_gap(db, gap_id)


@router.post("/gaps/{gap_id}/dismiss")
def dismiss_gap(
    gap_id: uuid.UUID,
    body: DismissBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> GapActionOut:
    return service.dismiss_gap(db, session.user, gap_id, body.reason, request)


@router.post("/gaps/{gap_id}/reopen")
def reopen_gap(
    gap_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> GapActionOut:
    return service.reopen_gap(db, session.user, gap_id, request)
