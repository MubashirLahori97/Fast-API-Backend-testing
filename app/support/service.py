"""Support and consultation requests (story 10.1), and the support team's side of them (Super
Admin story 5.1).

Requests come from two places:

- the client's forms, Contact support team and Consult with support team (`send_request`);
- a conversation, when the Oracle couldn't answer a question (a knowledge gap) or the client
  asked for a person, and the client agreed to send it (`create_from_conversation`, which the
  conversations package calls).

Each one is saved with a job that emails the support team within a minute (NOTIFY_TEAM_JOB,
app/support/jobs.py). The email names only the type and the request's id; the team reads the
rest in the admin panel. A request's message and the team's notes are health data: never
logged, audited or emailed. The audit events hold the type and the id only.

The functions under "The support team's side" are for Phase A's admin endpoints, which don't
exist yet.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import get_args

from fastapi import Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.auth.models import User
from app.conversations.models import Conversation, Message
from app.core import audit, jobs
from app.core.config import settings
from app.core.errors import AppError, database_errors_retryable
from app.core.schemas import clean_message
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.support.models import SupportRequest
from app.support.schemas import (
    AboutProfile,
    AccountType,
    ClientOut,
    ConversationKind,
    Kind,
    Status,
    SupportRequestBody,
    SupportRequestDetail,
    SupportRequestPage,
    SupportRequestSent,
    SupportRequestSummary,
)

NOTIFY_TEAM_JOB = "support.notify_team"  # see app/support/jobs.py

# Story 10.1's confirmations.
REQUEST_SENT = (
    "Thanks, your message has been sent. The support team will reply by email within one "
    "business day."
)
CONSULTATION_SENT = (
    "Thanks, the support team will get in touch by email to talk about the next steps."
)
SENT_FROM_CONVERSATION = (
    "I’ve let the support team know. They’ll get back to you by email within one business day."
)
SEND_FAILED = "We couldn’t send your message just now. Please try again."
# Not in the stories (docs/decisions/10.1-support.md).
TOO_MANY_REQUESTS = (
    "You’ve sent a lot of messages to the support team in the last hour. Please try again later."
)
CONSULTATION_NOT_FOR_TEENS = "Consult with support team isn’t available on a teen account."
NOT_SENDABLE = "This message can’t be sent to the support team."
PROFILE_NOT_FOUND = "We couldn’t find that profile."
CONVERSATION_NOT_FOUND = "We couldn’t find that conversation."
MESSAGE_NOT_FOUND = "We couldn’t find that message."
REQUEST_NOT_FOUND = "We couldn’t find that request."
NOT_ALLOWED = "Only the support team can do that."
# Super Admin story 5.1's confirmations.
RESOLVED = "This request has been marked as resolved."
REOPENED = "This request has been reopened."
NOTE_SAVED = "Your note has been saved."

# The admin list shows the start of each message.
FIRST_LINE_MAX_LENGTH = 120
TEAM_ROLES = frozenset({"admin", "super_admin"})


def is_teen_account(account: User) -> bool:
    """A teen with their own account (story 1.5): users.account_type, which app/teens/ sets. It
    stays "teen" after the age of majority until the teen creates their adult account (1.6)."""
    return account.account_type == "teen"


def _confirmation(support_request: SupportRequest) -> str:
    if support_request.source == "conversation":
        return SENT_FROM_CONVERSATION
    if support_request.kind == "consultation":
        return CONSULTATION_SENT
    return REQUEST_SENT


def _sent(support_request: SupportRequest) -> SupportRequestSent:
    return SupportRequestSent(
        id=support_request.id,
        kind=support_request.kind,
        status=support_request.status,
        profile_id=support_request.profile_id,
        created_at=support_request.created_at,
        message=_confirmation(support_request),
    )


@contextmanager
def _send_errors(db: Session) -> Iterator[None]:
    """Story 10.1's "Sending failed" for any database error: the client can try again. The
    error's own text isn't kept, since it can quote the message."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "send_failed", SEND_FAILED) from None


def _check_rate(db: Session, account: User) -> None:
    """Every request emails the support team, so each account has an hourly limit."""
    sent = db.scalar(
        select(func.count())
        .select_from(SupportRequest)
        .where(
            SupportRequest.account_id == account.id,
            SupportRequest.created_at > datetime.now(UTC) - timedelta(hours=1),
        )
    )
    if sent >= settings.max_support_requests_per_hour:
        raise AppError(429, "too_many_support_requests", TOO_MANY_REQUESTS)


def _add(
    db: Session,
    account: User,
    profile: Profile | None,
    request: Request | None,
    **fields: object,
) -> SupportRequest:
    """Adds the request, the job that emails the team, and the audit event (type and id
    only). They're saved together by the caller's commit, so the team is only told about a
    request that was saved."""
    support_request = SupportRequest(
        account_id=account.id, profile_id=profile.id if profile else None, **fields
    )
    db.add(support_request)
    db.flush()
    jobs.enqueue(db, NOTIFY_TEAM_JOB, {"support_request_id": str(support_request.id)})
    # The admin panel's alert (Super Admin 11.1). Only the request's type: what the client
    # wrote can be health data, so it stays in the request's own screen.
    from app.admin.notifications import notify_admins  # here: admin imports this package

    notify_admins(
        db,
        "support_request",
        {"request_type": support_request.kind},
        target_id=support_request.id,
    )
    audit.record(
        db,
        "support.request_sent",
        actor_id=account.id,
        target_type="support_request",
        target_id=support_request.id,
        request=request,
        details={"kind": support_request.kind},
    )
    return support_request


# The client's forms


def send_request(
    db: Session,
    account: User,
    profile: Profile | None,
    body: SupportRequestBody,
    request: Request,
) -> tuple[SupportRequestSent, bool]:
    """Story 10.1's Contact support team and Consult with support team forms. `profile` is
    the active profile the request is about (the router has checked it's the account's own),
    or None when the client has none. Returns (result, created); safe to repeat with the same
    client_request_id, so a request kept while offline is sent once."""
    with _send_errors(db):
        # One request at a time per account, so the resend check and the hourly limit hold.
        db.refresh(account, with_for_update=True)
        existing = db.scalar(
            select(SupportRequest).where(
                SupportRequest.account_id == account.id,
                SupportRequest.client_request_id == body.client_request_id,
            )
        )
        if existing is not None:
            return _sent(existing), False
        # Story 10.1: teens with their own account don't see Consult with support team.
        if body.kind == "consultation" and is_teen_account(account):
            raise AppError(403, "consultation_not_available", CONSULTATION_NOT_FOR_TEENS)
        _check_rate(db, account)
        support_request = _add(
            db,
            account,
            profile,
            request,
            kind=body.kind,
            source="form",
            message=body.message,
            client_request_id=body.client_request_id,
        )
        db.commit()
    return _sent(support_request), True


# Story 11.1's Email Change Request, sent from Profile & Account by the accounts package


def open_email_change(db: Session, account: User) -> SupportRequest | None:
    """The account's email change request that the team hasn't done yet, if any."""
    return db.scalar(
        select(SupportRequest).where(
            SupportRequest.account_id == account.id,
            SupportRequest.kind == "email_change",
            SupportRequest.status == "open",
        )
    )


def add_email_change(
    db: Session,
    account: User,
    requested_email: str,
    client_request_id: uuid.UUID,
    request: Request | None,
) -> SupportRequest:
    """Adds an Email Change Request for the team (Super Admin 5.1), with its team email and
    audit event, under the same hourly limit as the other requests. The caller holds the
    account row lock, has checked the address, and commits."""
    _check_rate(db, account)
    return _add(
        db,
        account,
        None,
        request,
        kind="email_change",
        source="form",
        message="",
        client_request_id=client_request_id,
        requested_email=requested_email,
    )


def mark_email_change_done(
    db: Session, admin: User, support_request: SupportRequest, request: Request | None
) -> None:
    """Super Admin 5.1: an Email Change Request is resolved automatically once the email is
    changed. The caller holds the request's row lock and commits."""
    _check_team_member(admin)
    support_request.status = "resolved"
    support_request.resolved_at = datetime.now(UTC)
    support_request.resolved_by_id = admin.id
    _audit_team_action(db, "support.request_resolved", support_request, admin, request)


# From a conversation


def _source_message(
    db: Session, conversation: Conversation, message_id: uuid.UUID | None
) -> Message:
    """The client message to send. By default, the one the Oracle's latest reply answers: the
    question it couldn't answer, or the client asking for a person, which that reply offered
    to send."""
    if message_id is None:
        offer = db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role == "oracle",
                Message.reply_to_id.is_not(None),
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        message_id = offer.reply_to_id if offer is not None else None
    message = db.get(Message, message_id) if message_id is not None else None
    if message is None or message.conversation_id != conversation.id or message.role != "client":
        raise AppError(404, "message_not_found", MESSAGE_NOT_FOUND)
    return message


def _from_message(db: Session, message: Message, kind: str) -> SupportRequest | None:
    return db.scalar(
        select(SupportRequest).where(
            SupportRequest.source_message_id == message.id, SupportRequest.kind == kind
        )
    )


def create_from_conversation(
    db: Session,
    account: User,
    profile: Profile,
    conversation_id: uuid.UUID,
    kind: ConversationKind,
    *,
    message_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> SupportRequestSent:
    """Story 10.1: the client agreed to send something from a conversation to the support
    team. `kind` is "knowledge_gap" (a question the Oracle couldn't answer; it also becomes a
    knowledge gap for Super Admin story 6.3) or "talk_to_support" (the client asked for a
    person).

    The message sent is `message_id`, a client message in the conversation, or by default the
    one the Oracle's latest reply answers (see _source_message): call this before the reply
    to the client's "yes" is saved, or pass the id. Sending the same message twice returns
    the first request. The result's `message` is the line to show the client.

    Refused (AppError) when the conversation isn't this profile's, the profile can't be used,
    or the message wasn't found safe by the safety check (story 10.1: an emergency, crisis
    or urgent concern gets the safety path and an escalation, never a support request).

    Adds the request, its email job and its audit event to the session without committing:
    the caller commits, with its own changes, and turns database errors into SEND_FAILED."""
    if kind not in get_args(ConversationKind):
        raise ValueError(f"Unknown kind for a request from a conversation: {kind}")
    if profile.account_id != account.id:
        raise AppError(404, "profile_not_found", PROFILE_NOT_FOUND)
    check_can_use(profile)
    conversation = db.get(Conversation, conversation_id)
    if (
        conversation is None
        or conversation.deleted_at is not None
        or conversation.profile_id != profile.id
    ):
        raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
    message = _source_message(db, conversation, message_id)
    if message.safety_level != "none":
        raise AppError(409, "not_sendable", NOT_SENDABLE)

    existing = _from_message(db, message, kind)
    if existing is not None:
        return _sent(existing)
    _check_rate(db, account)
    try:
        # A savepoint: if the same message is being sent at the same moment, only this
        # insert is undone, not the caller's own changes.
        with db.begin_nested():
            support_request = _add(
                db,
                account,
                profile,
                request,
                kind=kind,
                source="conversation",
                message=message.text,
                conversation_id=conversation.id,
                source_message_id=message.id,
            )
    except IntegrityError:
        existing = _from_message(db, message, kind)
        if existing is None:
            raise
        return _sent(existing)
    return _sent(support_request)


# The support team's side (Super Admin story 5.1), for Phase A's admin endpoints. The callers
# check the admin's sign-in; these functions check the role again, because the requests hold
# health data.


def _check_team_member(admin: User) -> None:
    if admin.role not in TEAM_ROLES:
        raise AppError(403, "not_allowed", NOT_ALLOWED)


def account_type(account: User) -> AccountType:
    return "teen" if is_teen_account(account) else "adult"


def _about(profile: Profile | None) -> AboutProfile | None:
    if profile is None:
        return None
    return AboutProfile(
        id=profile.id,
        is_self=profile.is_self,
        first_name=profile.first_name,
        relationship=profile.family_relationship,
    )


def _first_line(message: str) -> str:
    line = next((line.strip() for line in message.splitlines() if line.strip()), "")
    if len(line) > FIRST_LINE_MAX_LENGTH:
        return line[: FIRST_LINE_MAX_LENGTH - 1].rstrip() + "…"
    return line


def _summary_fields(support_request: SupportRequest) -> dict:
    account = support_request.account
    profile = _about(support_request.profile)
    if profile is not None and profile.is_self:
        # The client's own name lives on the account.
        profile = profile.model_copy(update={"first_name": account.first_name})
    return {
        "id": support_request.id,
        "kind": support_request.kind,
        "status": support_request.status,
        "client": ClientOut(
            id=account.id,
            first_name=account.first_name,
            email=account.email,
            account_type=account_type(account),
        ),
        "profile": profile,
        "first_line": _first_line(support_request.message),
        "received_at": support_request.created_at,
    }


def summary_out(support_request: SupportRequest) -> SupportRequestSummary:
    return SupportRequestSummary(**_summary_fields(support_request))


def detail_out(support_request: SupportRequest) -> SupportRequestDetail:
    return SupportRequestDetail(
        **_summary_fields(support_request),
        message=support_request.message,
        source=support_request.source,
        conversation_id=support_request.conversation_id,
        requested_email=support_request.requested_email,
        internal_notes=support_request.internal_notes,
        team_notified_at=support_request.team_notified_at,
        resolved_at=support_request.resolved_at,
        resolved_by_id=support_request.resolved_by_id,
    )


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_requests(
    db: Session,
    admin: User,
    *,
    kind: Kind | None = None,
    status: Status | None = None,
    account_type: AccountType | None = None,
    search: str | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SupportRequestPage:
    """The team's list: open requests first, oldest first. Search matches the client's first
    name or email; the filters are type, status, account type and when it was received."""
    _check_team_member(admin)
    query = select(SupportRequest).join(User, SupportRequest.account_id == User.id)
    if kind is not None:
        query = query.where(SupportRequest.kind == kind)
    if status is not None:
        query = query.where(SupportRequest.status == status)
    if account_type is not None:
        # The same rule as is_teen_account.
        query = query.where(User.account_type == ("teen" if account_type == "teen" else "adult"))
    if search and search.strip():
        pattern = _like(search.strip())
        query = query.where(
            or_(
                User.first_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if received_from is not None:
        query = query.where(SupportRequest.created_at >= received_from)
    if received_to is not None:
        query = query.where(SupportRequest.created_at <= received_to)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.options(selectinload(SupportRequest.account), selectinload(SupportRequest.profile))
        .order_by(
            case((SupportRequest.status == "open", 0), else_=1),
            SupportRequest.created_at,
            SupportRequest.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return SupportRequestPage(items=[summary_out(row) for row in rows], total=total)


def open_counts(db: Session, admin: User) -> dict[str, int]:
    """Open requests by type, for the Dashboard's Needs Attention strip (Super Admin 2.1)."""
    _check_team_member(admin)
    counts = dict(
        db.execute(
            select(SupportRequest.kind, func.count())
            .where(SupportRequest.status == "open")
            .group_by(SupportRequest.kind)
        ).all()
    )
    return {kind: counts.get(kind, 0) for kind in get_args(Kind)}


def _load(db: Session, request_id: uuid.UUID, *, for_update: bool = False) -> SupportRequest:
    support_request = db.get(SupportRequest, request_id, with_for_update=for_update)
    if support_request is None:
        raise AppError(404, "support_request_not_found", REQUEST_NOT_FOUND)
    return support_request


def _audit_team_action(
    db: Session,
    action: str,
    support_request: SupportRequest,
    admin: User,
    request: Request | None,
) -> None:
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="support_request",
        target_id=support_request.id,
        request=request,
        details={"kind": support_request.kind},
    )


def get_request(
    db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None
) -> SupportRequestDetail:
    """A request's details. Every view is recorded in the audit log (Super Admin 5.1)."""
    _check_team_member(admin)
    support_request = _load(db, request_id)
    with database_errors_retryable(db):
        _audit_team_action(db, "support.request_viewed", support_request, admin, request)
        db.commit()
    return detail_out(support_request)


def save_notes(
    db: Session,
    admin: User,
    request_id: uuid.UUID,
    notes: str | None,
    request: Request | None = None,
) -> str:
    """Replaces the team's internal notes, for example "Emailed on 2 Nov". The endpoint's
    schema limits their length. The audit event says a note was saved, never what it says."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        support_request = _load(db, request_id, for_update=True)
        support_request.internal_notes = clean_message(notes or "") or None
        _audit_team_action(db, "support.request_note_saved", support_request, admin, request)
        db.commit()
    return NOTE_SAVED


def resolve(db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None) -> str:
    """Mark as resolved, recording who and when. Resolving a resolved request changes
    nothing."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        support_request = _load(db, request_id, for_update=True)
        if support_request.status != "resolved":
            support_request.status = "resolved"
            support_request.resolved_at = datetime.now(UTC)
            support_request.resolved_by_id = admin.id
            _audit_team_action(db, "support.request_resolved", support_request, admin, request)
        db.commit()
    return RESOLVED


def reopen(db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None) -> str:
    """Reopens a resolved request. Reopening an open request changes nothing."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        support_request = _load(db, request_id, for_update=True)
        if support_request.status != "open":
            support_request.status = "open"
            support_request.resolved_at = None
            support_request.resolved_by_id = None
            _audit_team_action(db, "support.request_reopened", support_request, admin, request)
        db.commit()
    return REOPENED
