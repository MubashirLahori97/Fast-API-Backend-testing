"""Knowledge Base Management (Super Admin and Admin stories 6.1 to 6.3, 6 Nov 19:22).

Who can do what:

- Admins and the Super Admin: view, add, edit, archive, restore and roll back content; upload
  files; see, dismiss and reopen knowledge gaps, and add answers.
- Only the Super Admin publishes, approves or rejects content (enforced here, not only hidden).
  An Admin's Send for approval saves the version as Pending approval and tells the Super Admin;
  the Oracle keeps using the version published before, if any. An Admin's Publish gets 403. The
  Admin who sent it is told of the decision (Admin 7.1). An Admin may roll back only to a version
  that was published before (already approved); anything new goes through approval.
- Knowledge gaps: an Admin's answer sent for approval makes a New gap Answer pending; approving
  it marks the gap Answered; rejecting it sends the gap back to New, with the reason on the
  answer. Rejected items stay in the listing as Rejected.

Saving: a draft or a version waiting for approval is edited in place (so a draft published
later is still version 1, as 6.2 says); any other save adds a version. A roll back publishes a
copy of the earlier version as a new one, so the history stays in order, and leaves any open
draft or pending version as superseded.

Every addition, draft, edit, approval, rejection, archive, restore, roll back, upload, gap
dismissal and reopening is audited (ids, statuses and version numbers only). Every change to
what the Oracle uses is given to it before the commit (`knowledge.deliver`); nothing is synced
by a job, and an Oracle failure cancels the change with "We couldn't do that just now".
"""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import Request, UploadFile
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, undefer

from app.admin.common import day_range, like
from app.admin.knowledge.schemas import (
    AddAnswerPrefill,
    AnswerContentRef,
    ContentDetail,
    ContentEdit,
    ContentNew,
    ContentPage,
    ContentRow,
    ContentSaved,
    ContentStatus,
    ContentType,
    FileOut,
    GapActionOut,
    GapDetail,
    GapPage,
    GapRef,
    GapRow,
    GapStatus,
    KnowledgeScreen,
    PersonRef,
    VersionDetail,
    VersionOut,
)
from app.admin.notifications.service import notify_admins
from app.auth.models import User
from app.core import audit
from app.core.config import settings
from app.core.errors import AppError, database_errors_retryable
from app.core.schemas import clean_line
from app.knowledge import service as knowledge
from app.knowledge.models import (
    KnowledgeContent,
    KnowledgeContentVersion,
    KnowledgeFile,
    KnowledgeGap,
)
from app.oracle.contract import Oracle

# Super Admin and Admin 6.1 to 6.3's messages.
NO_CONTENT_RESULTS = "No content matches your search."
APPROVED = "This content has been published. The Oracle will start using it shortly."
PUBLISHED = "Your content has been published. The Oracle will start using it shortly."
SENT_FOR_APPROVAL = "Your content has been sent to the Super Admin for approval."  # Admin 6.2
EDIT_SENT_FOR_APPROVAL = "Your changes have been sent to the Super Admin for approval."  # Admin 6.1
ANSWER_SENT = "Your answer has been sent to the Super Admin for approval."  # Admin 6.3
DRAFT_SAVED = "Your draft has been saved."
ARCHIVE_CONFIRMATION = (
    "Archive this content? The Oracle will stop using it, but you can restore it later."
)
ROLLBACK_CONFIRMATION = "Publish version {number} instead of the current version?"
UNSUPPORTED_FILE = "This file type isn’t supported. Please upload a PDF, Word or text file."
FILE_TOO_LARGE = "This file is too large. Please upload a smaller file."
UPLOAD_FAILED = "We couldn’t upload this file. Please try again."
NO_GAPS = "There are no knowledge gaps right now."
GAP_ANSWERED = "This gap has been answered. The Oracle will start using your answer shortly."
GAP_DISMISSED = "This gap has been dismissed."
GAP_REOPENED = "This gap has been reopened."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
REJECTED = "This content has been rejected."
ARCHIVED = "This content has been archived."
RESTORED = "This content has been restored."
ROLLED_BACK = "Version {number} has been published again. The Oracle will start using it shortly."
NOTHING_PENDING = "There’s nothing waiting for approval on this content."
ARCHIVED_NOT_EDITABLE = "Archived content can’t be changed. Please restore it first."
ROLLBACK_CURRENT = "This version is already the one the Oracle uses."
ROLLBACK_NOT_APPROVED = (
    "Only a version that was published before can be published again. Please edit the content "
    "instead, and it will be sent for approval."
)
GAP_NOT_DISMISSED = "Only a dismissed gap can be reopened."
CONTENT_NOT_FOUND = "We couldn’t find that content."
VERSION_NOT_FOUND = "We couldn’t find that version."
FILE_NOT_FOUND = "We couldn’t find that file. Please upload it again."
GAP_NOT_FOUND = "We couldn’t find that knowledge gap."
SUPER_ADMIN_ONLY = "Only the Super Admin can do this."
NOT_FOR_SUPER_ADMIN = "Please choose Save as draft or Publish."
# Uploads: what each allowed extension must be, by its first bytes.
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
UPLOAD_TYPES = {"pdf": "application/pdf", "docx": DOCX, "txt": "text/plain", "md": "text/plain"}
NAME_MAX_LENGTH = 200


def _now() -> datetime:
    return datetime.now(UTC)


def _is_super_admin(admin: User) -> bool:
    return admin.role == "super_admin"


def _check_super_admin(admin: User) -> None:
    if not _is_super_admin(admin):
        raise AppError(403, "super_admin_only", SUPER_ADMIN_ONLY)


def _audit(db: Session, action: str, item_id: uuid.UUID, admin: User, request, **details):
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="knowledge_content",
        target_id=item_id,
        request=request,
        details=details or None,
    )


# Reading


def _person(db: Session, user_id: uuid.UUID | None) -> PersonRef | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return PersonRef(id=user_id, first_name=user.first_name if user else None)


def _file_out(file: KnowledgeFile | None) -> FileOut | None:
    if file is None:
        return None
    return FileOut(
        id=file.id,
        name=file.name,
        media_type=file.media_type,
        size_bytes=file.size_bytes,
        uploaded_at=file.created_at,
    )


def _row(item: KnowledgeContent) -> ContentRow:
    return ContentRow(
        id=item.id,
        title=item.title,
        content_type=item.content_type,
        status=item.status,
        version=item.latest_version,
        live_version=knowledge.live_version_number(item),
        updated_at=item.updated_at,
    )


def _version_out(db: Session, version: KnowledgeContentVersion) -> VersionOut:
    return VersionOut(
        number=version.number,
        title=version.title,
        content_type=version.content_type,
        status=version.status,
        rejection_reason=version.rejection_reason,
        rolled_back_from=version.rolled_back_from,
        has_file=version.file_id is not None,
        created_by=_person(db, version.created_by_id),
        created_at=version.created_at,
        updated_at=version.updated_at,
        reviewed_by=_person(db, version.reviewed_by_id),
        reviewed_at=version.reviewed_at,
        published_at=version.published_at,
        rollback_confirmation=ROLLBACK_CONFIRMATION.format(number=version.number),
    )


def _version(
    db: Session, item: KnowledgeContent, number: int, *, lock: bool = False
) -> KnowledgeContentVersion:
    query = (
        select(KnowledgeContentVersion)
        .where(
            KnowledgeContentVersion.content_id == item.id,
            KnowledgeContentVersion.number == number,
        )
        .options(undefer(KnowledgeContentVersion.text))
    )
    if lock:
        query = query.with_for_update()
    version = db.scalar(query)
    if version is None:
        raise AppError(404, "version_not_found", VERSION_NOT_FOUND)
    return version


def _load(db: Session, content_id: uuid.UUID, *, lock: bool = False) -> KnowledgeContent:
    item = db.get(KnowledgeContent, content_id, with_for_update=lock)
    if item is None:
        raise AppError(404, "content_not_found", CONTENT_NOT_FOUND)
    return item


def _detail(db: Session, item: KnowledgeContent, viewer: User) -> ContentDetail:
    versions = list(
        db.scalars(
            select(KnowledgeContentVersion)
            .where(KnowledgeContentVersion.content_id == item.id)
            .order_by(KnowledgeContentVersion.number.desc())
        )
    )
    latest = _version(db, item, item.latest_version)
    gap = db.get(KnowledgeGap, item.knowledge_gap_id) if item.knowledge_gap_id else None
    return ContentDetail(
        **_row(item).model_dump(),
        text=latest.text,
        file=_file_out(latest.file),
        rejection_reason=latest.rejection_reason,
        knowledge_gap=GapRef(id=gap.id, question=gap.question, status=gap.status) if gap else None,
        versions=[_version_out(db, version) for version in versions],
        can_review=_is_super_admin(viewer) and item.status == "pending_approval",
        archive_confirmation=ARCHIVE_CONFIRMATION,
    )


def screen(db: Session) -> KnowledgeScreen:
    pending = db.scalar(
        select(func.count())
        .select_from(KnowledgeContent)
        .where(KnowledgeContent.status == "pending_approval")
    )
    return KnowledgeScreen(new_gaps=knowledge.new_gap_count(db), pending_approval=pending)


def list_contents(
    db: Session,
    *,
    search: str | None = None,
    content_type: ContentType | None = None,
    status: ContentStatus | None = None,
    updated_from=None,
    updated_to=None,
    limit: int = 50,
    offset: int = 0,
) -> ContentPage:
    """6.1's listing: Pending approval first, then newest first. Search matches the title or
    words in the latest version's text."""
    query = select(KnowledgeContent)
    if search and search.strip():
        pattern = like(search.strip())
        in_text = exists().where(
            KnowledgeContentVersion.content_id == KnowledgeContent.id,
            KnowledgeContentVersion.number == KnowledgeContent.latest_version,
            KnowledgeContentVersion.text.ilike(pattern, escape="\\"),
        )
        query = query.where(or_(KnowledgeContent.title.ilike(pattern, escape="\\"), in_text))
    if content_type is not None:
        query = query.where(KnowledgeContent.content_type == content_type)
    if status is not None:
        query = query.where(KnowledgeContent.status == status)
    start, end = day_range(updated_from, updated_to)
    if start is not None:
        query = query.where(KnowledgeContent.updated_at >= start)
    if end is not None:
        query = query.where(KnowledgeContent.updated_at < end)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(
        query.order_by(
            case((KnowledgeContent.status == "pending_approval", 0), else_=1),
            KnowledgeContent.updated_at.desc(),
            KnowledgeContent.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    rows = [_row(item) for item in items]
    return ContentPage(items=rows, total=total, message=None if rows else NO_CONTENT_RESULTS)


def get_content(db: Session, viewer: User, content_id: uuid.UUID) -> ContentDetail:
    return _detail(db, _load(db, content_id), viewer)


def get_version(db: Session, content_id: uuid.UUID, number: int) -> VersionDetail:
    """An earlier version from the history, to read."""
    item = _load(db, content_id)
    version = _version(db, item, number)
    return VersionDetail(
        **_version_out(db, version).model_dump(),
        text=version.text,
        file=_file_out(version.file),
    )


# Saving


def _check_file(db: Session, file_id: uuid.UUID | None) -> None:
    if file_id is not None and db.get(KnowledgeFile, file_id) is None:
        raise AppError(422, "file_not_found", FILE_NOT_FOUND, "file_id")


def _status_for(admin: User, action: str) -> str:
    """Save as draft for everyone; Publish for the Super Admin only; Send for approval for
    Admins only (Super Admin 6.2 and Admin 6.2's buttons)."""
    if action == "draft":
        return "draft"
    if _is_super_admin(admin):
        if action != "publish":
            raise AppError(422, "invalid_action", NOT_FOR_SUPER_ADMIN, "action")
        return "published"
    if action == "publish":
        raise AppError(403, "super_admin_only", SUPER_ADMIN_ONLY, "action")
    return "pending_approval"


def _publish(
    db: Session, admin: User, item: KnowledgeContent, version: KnowledgeContentVersion
) -> bool:
    """Makes `version` the one the Oracle uses. Returns True when it answered a knowledge gap."""
    now = _now()
    version.status = "published"
    version.published_at = now
    version.rejection_reason = None
    version.reviewed_by_id = admin.id
    version.reviewed_at = now
    item.published_version = version.number
    return knowledge.mark_gap_answered(db, item, admin.id)


def _refresh_item(item: KnowledgeContent, latest: KnowledgeContentVersion) -> None:
    item.title = latest.title
    item.content_type = latest.content_type
    item.status = "archived" if item.archived_at is not None else latest.status
    item.updated_at = _now()


def _saved_message(status: str, answered: bool, item: KnowledgeContent, *, edit: bool) -> str:
    if status == "draft":
        return DRAFT_SAVED
    if status == "pending_approval":
        if item.knowledge_gap_id is not None:
            return ANSWER_SENT
        return EDIT_SENT_FOR_APPROVAL if edit else SENT_FOR_APPROVAL
    return GAP_ANSWERED if answered else PUBLISHED


def _after_save(db: Session, admin: User, item: KnowledgeContent, status: str) -> None:
    if status == "pending_approval":
        # Super Admin 11.1: content waiting for approval (the Super Admin only).
        notify_admins(db, "content_pending_approval", target_id=item.id)
        # Admin 6.3: an answer sent for a New gap makes it Answer pending.
        knowledge.mark_gap_answer_pending(db, item, admin.id)


def create_content(
    db: Session, admin: User, body: ContentNew, oracle: Oracle, request: Request | None = None
) -> ContentSaved:
    """6.2's Add Content (and 6.3's Add answer). Saved as Draft, Published (Super Admin), or
    Pending approval (an Admin's Send for approval). Published content linked to a gap marks it
    Answered; an Admin's answer makes the gap Answer pending."""
    status = _status_for(admin, body.action)
    with database_errors_retryable(db):
        if (
            body.knowledge_gap_id is not None
            and db.get(KnowledgeGap, body.knowledge_gap_id) is None
        ):
            raise AppError(404, "knowledge_gap_not_found", GAP_NOT_FOUND, "knowledge_gap_id")
        _check_file(db, body.file_id)
        item = KnowledgeContent(
            title=body.title,
            content_type=body.content_type,
            status="draft",
            latest_version=1,
            knowledge_gap_id=body.knowledge_gap_id,
            created_by_id=admin.id,
        )
        db.add(item)
        db.flush()
        version = KnowledgeContentVersion(
            content_id=item.id,
            number=1,
            title=body.title,
            content_type=body.content_type,
            text=body.text,
            file_id=body.file_id,
            status="draft" if status == "published" else status,
            created_by_id=admin.id,
            updated_by_id=admin.id,
        )
        answered = False
        if status == "published":
            answered = _publish(db, admin, item, version)
        db.add(version)
        _refresh_item(item, version)
        _audit(
            db,
            "knowledge.content_added",
            item.id,
            admin,
            request,
            status=version.status,
            content_type=version.content_type,
            version=1,
        )
        _after_save(db, admin, item, version.status)
        if status == "published":
            knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(
        content=_detail(db, item, admin),
        message=_saved_message(status, answered, item, edit=False),
    )


def edit_content(
    db: Session,
    admin: User,
    content_id: uuid.UUID,
    body: ContentEdit,
    oracle: Oracle,
    request: Request | None,
) -> ContentSaved:
    """6.1's Edit. Saving creates a new version (a draft or pending version is updated in
    place). The Super Admin's Publish publishes straight away; an Admin's waits for approval."""
    status = _status_for(admin, body.action)
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        if item.archived_at is not None:
            raise AppError(409, "content_archived", ARCHIVED_NOT_EDITABLE)
        _check_file(db, body.file_id)
        latest = _version(db, item, item.latest_version, lock=True)
        if latest.status in ("draft", "pending_approval"):
            version = latest
            version.updated_by_id = admin.id
        else:
            item.latest_version += 1
            version = KnowledgeContentVersion(
                content_id=item.id,
                number=item.latest_version,
                created_by_id=admin.id,
                updated_by_id=admin.id,
            )
            db.add(version)
        version.title = body.title
        version.content_type = body.content_type
        version.text = body.text
        version.file_id = body.file_id
        version.rejection_reason = None
        version.reviewed_by_id = None
        version.reviewed_at = None
        answered = False
        if status == "published":
            answered = _publish(db, admin, item, version)
        else:
            version.status = status
        db.flush()
        _refresh_item(item, version)
        _audit(
            db,
            "knowledge.content_edited",
            item.id,
            admin,
            request,
            status=version.status,
            version=version.number,
        )
        _after_save(db, admin, item, version.status)
        if status == "published":
            knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(
        content=_detail(db, item, admin),
        message=_saved_message(status, answered, item, edit=True),
    )


def _pending(db: Session, item: KnowledgeContent) -> KnowledgeContentVersion:
    latest = _version(db, item, item.latest_version, lock=True)
    if latest.status != "pending_approval" or item.archived_at is not None:
        raise AppError(409, "nothing_pending", NOTHING_PENDING)
    return latest


def _tell_sender(
    db: Session, admin: User, item: KnowledgeContent, version: KnowledgeContentVersion, kind: str
) -> None:
    """Admin 6.2 and 7.1: the Admin who sent the content is told of the decision (the Super
    Admin isn't told of their own)."""
    sender_id = version.updated_by_id or version.created_by_id
    if sender_id is not None and sender_id != admin.id:
        notify_admins(db, kind, target_id=item.id, recipient_id=sender_id)


def approve(
    db: Session, admin: User, content_id: uuid.UUID, oracle: Oracle, request: Request | None = None
) -> ContentSaved:
    """6.1's Approve & publish (Super Admin only): the Oracle starts using it."""
    _check_super_admin(admin)
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        version = _pending(db, item)
        answered = _publish(db, admin, item, version)
        _refresh_item(item, version)
        _audit(db, "knowledge.content_approved", item.id, admin, request, version=version.number)
        _tell_sender(db, admin, item, version, "content_approved")
        knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(
        content=_detail(db, item, admin), message=GAP_ANSWERED if answered else APPROVED
    )


def reject(
    db: Session, admin: User, content_id: uuid.UUID, reason: str, request: Request | None = None
) -> ContentSaved:
    """6.1's Reject with a reason (Super Admin only): it isn't published and shows as Rejected.
    A version published earlier stays in use."""
    _check_super_admin(admin)
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        version = _pending(db, item)
        version.status = "rejected"
        version.rejection_reason = reason
        version.reviewed_by_id = admin.id
        version.reviewed_at = _now()
        _refresh_item(item, version)
        _audit(db, "knowledge.content_rejected", item.id, admin, request, version=version.number)
        # 6.3: a rejected Admin answer sends its gap back to New, with the reason on the answer.
        knowledge.return_gap_to_new(db, item, admin.id)
        _tell_sender(db, admin, item, version, "content_rejected")
        db.commit()
    return ContentSaved(content=_detail(db, item, admin), message=REJECTED)


def archive(
    db: Session, admin: User, content_id: uuid.UUID, oracle: Oracle, request: Request | None = None
) -> ContentSaved:
    """6.1's Archive: the Oracle stops using it; it's kept, with its history."""
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        if item.archived_at is None:
            item.archived_at = _now()
            item.archived_by_id = admin.id
            item.status = "archived"
            item.updated_at = _now()
            _audit(db, "knowledge.content_archived", item.id, admin, request)
            if item.published_version is not None:
                knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(content=_detail(db, item, admin), message=ARCHIVED)


def restore(
    db: Session, admin: User, content_id: uuid.UUID, oracle: Oracle, request: Request | None = None
) -> ContentSaved:
    """6.1's Restore: an archived item comes back as it was (Published, if it had been)."""
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        if item.archived_at is not None:
            item.archived_at = None
            item.archived_by_id = None
            _refresh_item(item, _version(db, item, item.latest_version))
            _audit(db, "knowledge.content_restored", item.id, admin, request)
            if item.published_version is not None:
                knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(content=_detail(db, item, admin), message=RESTORED)


def roll_back(
    db: Session,
    admin: User,
    content_id: uuid.UUID,
    number: int,
    oracle: Oracle,
    request: Request | None = None,
) -> ContentSaved:
    """6.1's Roll back: publishes an earlier version again, as a new version copied from it.
    An Admin can only choose a version that was published before."""
    with database_errors_retryable(db):
        item = _load(db, content_id, lock=True)
        if item.archived_at is not None:
            raise AppError(409, "content_archived", ARCHIVED_NOT_EDITABLE)
        target = _version(db, item, number)
        if number == item.published_version == item.latest_version:
            raise AppError(409, "already_live", ROLLBACK_CURRENT, "version")
        if not _is_super_admin(admin) and target.status != "published":
            raise AppError(403, "rollback_needs_approval", ROLLBACK_NOT_APPROVED, "version")
        latest = _version(db, item, item.latest_version, lock=True)
        if latest.status in ("draft", "pending_approval"):
            latest.status = "superseded"
        item.latest_version += 1
        version = KnowledgeContentVersion(
            content_id=item.id,
            number=item.latest_version,
            title=target.title,
            content_type=target.content_type,
            text=target.text,
            file_id=target.file_id,
            rolled_back_from=target.number,
            created_by_id=admin.id,
            updated_by_id=admin.id,
        )
        _publish(db, admin, item, version)
        db.add(version)
        db.flush()
        _refresh_item(item, version)
        _audit(
            db,
            "knowledge.content_rolled_back",
            item.id,
            admin,
            request,
            from_version=target.number,
            version=version.number,
        )
        knowledge.deliver(db, item, oracle)
        db.commit()
    return ContentSaved(content=_detail(db, item, admin), message=ROLLED_BACK.format(number=number))


# Uploads (6.2)


def _media_type(name: str, data: bytes) -> str | None:
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    media_type = UPLOAD_TYPES.get(extension)
    if media_type == "application/pdf" and data.startswith(b"%PDF-"):
        return media_type
    if media_type == DOCX and data.startswith(b"PK\x03\x04"):
        return media_type
    if media_type == "text/plain" and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return media_type
    return None


def upload_file(
    db: Session, admin: User, upload: UploadFile, request: Request | None = None
) -> FileOut:
    """Stores an uploaded PDF, Word (DOCX) or text file in the app's own library (the
    database for now), checked by its extension and first bytes. Content then refers to it by
    id."""
    name = clean_line(upload.filename or "")[:NAME_MAX_LENGTH] or "upload"
    data = upload.file.read(settings.knowledge_upload_max_bytes + 1)
    if len(data) > settings.knowledge_upload_max_bytes:
        raise AppError(413, "file_too_large", FILE_TOO_LARGE, "file")
    media_type = _media_type(name, data) if data else None
    if media_type is None:
        raise AppError(415, "unsupported_file", UNSUPPORTED_FILE, "file")
    file = KnowledgeFile(
        name=name,
        media_type=media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        uploaded_by_id=admin.id,
    )
    try:
        db.add(file)
        db.flush()
        audit.record(
            db,
            "knowledge.file_uploaded",
            actor_id=admin.id,
            target_type="knowledge_file",
            target_id=file.id,
            request=request,
            details={"media_type": media_type, "size_bytes": len(data)},
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "upload_failed", UPLOAD_FAILED, "file") from None
    return _file_out(file)


def file_for_download(db: Session, file_id: uuid.UUID) -> KnowledgeFile:
    file = db.scalar(
        select(KnowledgeFile)
        .where(KnowledgeFile.id == file_id)
        .options(undefer(KnowledgeFile.data))
    )
    if file is None:
        raise AppError(404, "file_not_found", FILE_NOT_FOUND)
    return file


# Knowledge gaps (6.3)


def _gap_row(gap: KnowledgeGap) -> GapRow:
    return GapRow(
        id=gap.id,
        question=gap.question,
        topic=gap.topic,
        times_asked=gap.times_asked,
        status=gap.status,
        first_asked_at=gap.first_asked_at,
        last_asked_at=gap.last_asked_at,
    )


def list_gaps(
    db: Session,
    *,
    search: str | None = None,
    topic: str | None = None,
    status: GapStatus | None = None,
    asked_from=None,
    asked_to=None,
    limit: int = 50,
    offset: int = 0,
) -> GapPage:
    """6.3's listing: New first, most asked first. Shows only the question, never who asked.
    Search matches words in the question; filters are topic, status and when it was last
    asked."""
    query = select(KnowledgeGap)
    if search and search.strip():
        query = query.where(KnowledgeGap.question.ilike(like(search.strip()), escape="\\"))
    if topic and topic.strip():
        query = query.where(func.lower(KnowledgeGap.topic) == topic.strip().lower())
    if status is not None:
        query = query.where(KnowledgeGap.status == status)
    start, end = day_range(asked_from, asked_to)
    if start is not None:
        query = query.where(KnowledgeGap.last_asked_at >= start)
    if end is not None:
        query = query.where(KnowledgeGap.last_asked_at < end)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    gaps = db.scalars(
        query.order_by(
            case((KnowledgeGap.status == "new", 0), else_=1),
            KnowledgeGap.times_asked.desc(),
            KnowledgeGap.last_asked_at.desc(),
            KnowledgeGap.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    topics = db.scalars(
        select(KnowledgeGap.topic)
        .where(KnowledgeGap.topic.is_not(None))
        .group_by(KnowledgeGap.topic)
        .order_by(KnowledgeGap.topic)
    ).all()
    rows = [_gap_row(gap) for gap in gaps]
    return GapPage(items=rows, total=total, topics=list(topics), message=None if rows else NO_GAPS)


def _gap(db: Session, gap_id: uuid.UUID, *, lock: bool = False) -> KnowledgeGap:
    gap = db.get(KnowledgeGap, gap_id, with_for_update=lock)
    if gap is None:
        raise AppError(404, "knowledge_gap_not_found", GAP_NOT_FOUND)
    return gap


def _answer_ref(db: Session, answer: KnowledgeContent) -> AnswerContentRef:
    reason = None
    if answer.status == "rejected":
        reason = _version(db, answer, answer.latest_version).rejection_reason
    return AnswerContentRef(
        id=answer.id, title=answer.title, status=answer.status, rejection_reason=reason
    )


def _gap_detail(db: Session, gap: KnowledgeGap) -> GapDetail:
    answer = db.get(KnowledgeContent, gap.answer_content_id) if gap.answer_content_id else None
    return GapDetail(
        **_gap_row(gap).model_dump(),
        dismissed_reason=gap.dismissed_reason,
        dismissed_at=gap.dismissed_at,
        dismissed_by=_person(db, gap.dismissed_by_id),
        answered_at=gap.answered_at,
        answer_content=_answer_ref(db, answer) if answer else None,
        add_answer=AddAnswerPrefill(
            title=clean_line(gap.question)[: settings.knowledge_title_max_length],
            knowledge_gap_id=gap.id,
        ),
    )


def get_gap(db: Session, gap_id: uuid.UUID) -> GapDetail:
    return _gap_detail(db, _gap(db, gap_id))


def _audit_gap(db: Session, action: str, gap: KnowledgeGap, admin: User, request) -> None:
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="knowledge_gap",
        target_id=gap.id,
        request=request,
    )


def dismiss_gap(
    db: Session, admin: User, gap_id: uuid.UUID, reason: str, request: Request | None = None
) -> GapActionOut:
    """6.3's Dismiss, with a reason. Dismissed gaps stay in the listing and can be reopened."""
    with database_errors_retryable(db):
        gap = _gap(db, gap_id, lock=True)
        gap.status = "dismissed"
        gap.dismissed_reason = reason
        gap.dismissed_by_id = admin.id
        gap.dismissed_at = _now()
        gap.answered_at = None
        _audit_gap(db, "knowledge.gap_dismissed", gap, admin, request)
        db.commit()
    return GapActionOut(gap=_gap_detail(db, gap), message=GAP_DISMISSED)


def reopen_gap(
    db: Session, admin: User, gap_id: uuid.UUID, request: Request | None = None
) -> GapActionOut:
    """Reopens a dismissed gap as New (6.3: dismissed gaps can be reopened)."""
    with database_errors_retryable(db):
        gap = _gap(db, gap_id, lock=True)
        if gap.status == "answered":
            raise AppError(409, "gap_not_dismissed", GAP_NOT_DISMISSED)
        if gap.status == "dismissed":
            gap.status = "new"
            gap.dismissed_reason = None
            gap.dismissed_by_id = None
            gap.dismissed_at = None
            _audit_gap(db, "knowledge.gap_reopened", gap, admin, request)
        db.commit()
    return GapActionOut(gap=_gap_detail(db, gap), message=GAP_REOPENED)
