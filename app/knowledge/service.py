"""The knowledge base's own rules, used by the admin panel (app/admin/knowledge/) and the
worker: giving published content to the Oracle, and turning Knowledge Gap support requests into
knowledge gaps (Super Admin 6.1 to 6.3, Admin 6.1 to 6.3).

- **Delivery.** Nothing is synced automatically (6.2, 6 Nov 19:22): there's no sync job and no
  failed-sync alert. Publishing, approving, rolling back, archiving and restoring call
  `deliver` in the same request, after the change is flushed and before the commit: the Oracle
  gets the item's published version, or the item is withdrawn when it's archived. If the
  Oracle fails, the change is rolled back and the admin gets "We couldn’t do that just now.
  Please try again." (the stories' Action failed), so the knowledge base and the Oracle agree.
- **Knowledge gaps.** Client story 10.1 saves a Knowledge Gap support request when the client
  agrees to send an unanswered question (app/support/). The admin sweep (app/admin/jobs.py)
  takes each new one in within a minute: the Oracle says whether it's the same question as an
  earlier gap (`match_knowledge_gap`), and either the gap's count goes up or a new gap is made,
  and the team is told. Gap questions are clients' words: never logged, audited or put in a job
  payload or an email (the in-app admin notice shows it, as Super Admin 11.1 asks).
- **Gap statuses** follow the answer: an Admin's answer sent for approval makes the gap Answer
  pending; publishing it makes it Answered; rejecting it sends the gap back to New, with the
  reason on the answer.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, undefer

from app.admin.notifications.service import notify_admins
from app.core import audit
from app.core.config import settings
from app.core.errors import ACTION_FAILED, AppError
from app.core.schemas import clean_line
from app.knowledge.models import (
    KnowledgeContent,
    KnowledgeContentVersion,
    KnowledgeFile,
    KnowledgeGap,
    KnowledgeGapRequest,
)
from app.oracle.contract import KnowledgeDocument, KnowledgeGapCandidate, Oracle, OracleError
from app.support.models import SupportRequest

logger = logging.getLogger(__name__)

TOPIC_MAX_LENGTH = 60


def _now() -> datetime:
    return datetime.now(UTC)


# Giving published content to the Oracle


def live_version_number(item: KnowledgeContent) -> int | None:
    """The version the Oracle uses: the published one, unless the item is archived."""
    return item.published_version if item.archived_at is None else None


def _document(db: Session, item: KnowledgeContent, number: int) -> KnowledgeDocument:
    version = db.scalar(
        select(KnowledgeContentVersion)
        .where(
            KnowledgeContentVersion.content_id == item.id,
            KnowledgeContentVersion.number == number,
        )
        .options(undefer(KnowledgeContentVersion.text))
    )
    file = None
    if version.file_id is not None:
        file = db.scalar(
            select(KnowledgeFile)
            .where(KnowledgeFile.id == version.file_id)
            .options(undefer(KnowledgeFile.data))
        )
    return KnowledgeDocument(
        content_id=str(item.id),
        version=version.number,
        title=version.title,
        content_type=version.content_type,
        text=version.text,
        file_name=file.name if file else None,
        file_media_type=file.media_type if file else None,
        file_data=file.data if file else None,
    )


def deliver(db: Session, item: KnowledgeContent, oracle: Oracle) -> None:
    """Gives the Oracle what it should use for this item now: its published version, or nothing
    while it's archived or was never published. Call it after flushing the change, with the
    item's row lock held, before committing. On an Oracle failure (logged by class name only)
    the transaction is rolled back and the admin is asked to try again."""
    db.flush()
    live = live_version_number(item)
    try:
        if live is None:
            oracle.withdraw_knowledge(str(item.id))
        else:
            oracle.publish_knowledge(_document(db, item, live))
    except OracleError as exc:
        logger.warning("Knowledge base delivery failed: %s", type(exc).__name__)
        db.rollback()
        raise AppError(503, "action_failed", ACTION_FAILED) from None


def published_contents(
    db: Session, content_type: str | None = None
) -> list[tuple[KnowledgeContent, KnowledgeContentVersion]]:
    """What the Oracle uses now: each item that isn't archived, with its published version.
    For the parts of the app that show knowledge base content to clients, such as the Wellness
    Protocols in the Wellness Plan (Super Admin 6.1: archiving or editing a protocol updates
    what clients see)."""
    query = (
        select(KnowledgeContent, KnowledgeContentVersion)
        .join(
            KnowledgeContentVersion,
            (KnowledgeContentVersion.content_id == KnowledgeContent.id)
            & (KnowledgeContentVersion.number == KnowledgeContent.published_version),
        )
        .where(KnowledgeContent.archived_at.is_(None))
        .options(undefer(KnowledgeContentVersion.text))
        .order_by(KnowledgeContent.title)
    )
    if content_type is not None:
        query = query.where(KnowledgeContent.content_type == content_type)
    return [(item, version) for item, version in db.execute(query).all()]


# Knowledge gaps (Super Admin 6.3)


def _candidates(db: Session) -> list[KnowledgeGap]:
    return list(
        db.scalars(
            select(KnowledgeGap)
            .order_by(KnowledgeGap.last_asked_at.desc())
            .limit(settings.knowledge_gap_match_candidates)
        )
    )


def _audit_gap(db: Session, action: str, gap: KnowledgeGap) -> None:
    # The question is a client's words: the event holds the gap's id only.
    audit.record(db, action, target_type="knowledge_gap", target_id=gap.id)


def _take_in(db: Session, support_request: SupportRequest, oracle: Oracle) -> None:
    candidates = _candidates(db)
    match = oracle.match_knowledge_gap(
        support_request.message,
        [
            KnowledgeGapCandidate(gap_id=str(gap.id), question=gap.question, topic=gap.topic)
            for gap in candidates
        ],
    )
    known = {str(gap.id): gap.id for gap in candidates}
    gap = None
    if match.gap_id in known:
        gap = db.get(
            KnowledgeGap, known[match.gap_id], with_for_update=True, populate_existing=True
        )
    asked_at = support_request.created_at
    if gap is None:
        topic = clean_line(match.topic or "")[:TOPIC_MAX_LENGTH] or None
        gap = KnowledgeGap(
            question=support_request.message,
            topic=topic,
            first_asked_at=asked_at,
            last_asked_at=asked_at,
        )
        db.add(gap)
        db.flush()
        _audit_gap(db, "knowledge.gap_created", gap)
        notify_admins(db, "knowledge_gap", {"question": gap.question}, target_id=gap.id)
    else:
        gap.times_asked += 1
        gap.last_asked_at = max(gap.last_asked_at, asked_at)
        if gap.status == "answered":
            # 6.3: asked again after it was answered, so the answer didn't cover it.
            gap.status = "new"
            gap.answered_at = None
            _audit_gap(db, "knowledge.gap_reopened", gap)
            notify_admins(db, "knowledge_gap", {"question": gap.question}, target_id=gap.id)
        else:
            _audit_gap(db, "knowledge.gap_asked_again", gap)
    db.add(KnowledgeGapRequest(support_request_id=support_request.id, gap_id=gap.id))


def take_in_new_gaps(db: Session, oracle: Oracle) -> int:
    """Turns Knowledge Gap support requests not yet taken in into knowledge gaps, oldest first,
    committing each one. Stops at the first Oracle failure: the rest wait for the next sweep.
    Returns how many were taken in."""
    linked = exists().where(KnowledgeGapRequest.support_request_id == SupportRequest.id)
    ids = db.scalars(
        select(SupportRequest.id)
        .where(SupportRequest.kind == "knowledge_gap", ~linked)
        .order_by(SupportRequest.created_at)
        .limit(settings.knowledge_gap_batch_size)
    ).all()
    taken = 0
    for request_id in ids:
        support_request = db.get(SupportRequest, request_id, with_for_update=True)
        already = db.get(KnowledgeGapRequest, request_id)
        if support_request is None or already is not None:
            db.rollback()
            continue
        try:
            _take_in(db, support_request, oracle)
        except OracleError as exc:
            db.rollback()
            logger.warning("Knowledge gap match failed: %s", type(exc).__name__)
            break
        db.commit()
        taken += 1
    return taken


def new_gap_count(db: Session) -> int:
    """New knowledge gaps, for the Dashboard and the Knowledge Base screen."""
    return db.scalar(
        select(func.count()).select_from(KnowledgeGap).where(KnowledgeGap.status == "new")
    )


def mark_gap_answered(db: Session, item: KnowledgeContent, admin_id: uuid.UUID | None) -> bool:
    """6.2 and 6.3: content added from a knowledge gap was published, so the gap is Answered.
    Returns True when a gap was marked. The caller commits."""
    if item.knowledge_gap_id is None:
        return False
    gap = db.get(KnowledgeGap, item.knowledge_gap_id, with_for_update=True)
    if gap is None:
        return False
    if gap.status != "answered":
        gap.status = "answered"
        gap.answered_at = _now()
        gap.dismissed_at = None
        gap.dismissed_reason = None
        gap.dismissed_by_id = None
    gap.answer_content_id = item.id
    audit.record(
        db,
        "knowledge.gap_answered",
        actor_id=admin_id,
        target_type="knowledge_gap",
        target_id=gap.id,
        details={"content_id": str(item.id)},
    )
    return True


def _linked_gap(db: Session, item: KnowledgeContent) -> KnowledgeGap | None:
    if item.knowledge_gap_id is None:
        return None
    return db.get(KnowledgeGap, item.knowledge_gap_id, with_for_update=True)


def mark_gap_answer_pending(db: Session, item: KnowledgeContent, admin_id: uuid.UUID) -> bool:
    """6.3 (6 Nov 19:22): an Admin sent an answer to a New gap for approval, so the gap shows
    Answer pending until the Super Admin publishes it. Returns True when the gap changed. The
    caller commits."""
    gap = _linked_gap(db, item)
    if gap is None or gap.status != "new":
        return False
    gap.status = "answer_pending"
    gap.answer_content_id = item.id
    audit.record(
        db,
        "knowledge.gap_answer_pending",
        actor_id=admin_id,
        target_type="knowledge_gap",
        target_id=gap.id,
        details={"content_id": str(item.id)},
    )
    return True


def return_gap_to_new(db: Session, item: KnowledgeContent, admin_id: uuid.UUID) -> bool:
    """6.3's "Admin's answer is rejected": the gap goes back to New, with the reason on the
    answer (the gap keeps pointing at it, so its details show the reason). Returns True when
    the gap changed. The caller commits."""
    gap = _linked_gap(db, item)
    if gap is None or gap.status != "answer_pending" or gap.answer_content_id != item.id:
        return False
    gap.status = "new"
    audit.record(
        db,
        "knowledge.gap_answer_rejected",
        actor_id=admin_id,
        target_type="knowledge_gap",
        target_id=gap.id,
        details={"content_id": str(item.id)},
    )
    return True
