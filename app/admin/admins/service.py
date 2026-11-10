"""Admin Management (Super Admin 7.1 and 7.2).

An Admin is a row in `admin_invitations`, from the invite (Invite pending, Invite expired) to
the account it became (Active, Deactivated). Admins are deactivated, never deleted, so their
name stays on everything they did. Every change is audited, with the Super Admin as actor.

Locks: an invite's row for invite changes; the account's row for account changes.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.admins.schemas import (
    AdminDetails,
    AdminPage,
    AdminPermissions,
    AdminStatus,
    AdminSummary,
    DeactivateAdminIn,
    EditAdminIn,
    InviteAdminIn,
)
from app.admin.auth import emails
from app.admin.auth.models import AdminInvitation
from app.auth.models import (
    PasswordResetToken,
    TrustedDevice,
    User,
    UserSession,
    VerificationChallenge,
)
from app.auth.security import hash_secret, new_token
from app.auth.service import ADMIN_ROLES
from app.core import audit
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import AppError, database_errors_retryable

# Super Admin 7.1's and 7.2's messages.
NO_RESULTS = "No admins match your search."
ADMIN_EXISTS = "An admin with this email address already exists."
SEND_FAILED = "We couldn’t send the invite just now. Please try again."
# Not in the stories (docs/decisions/phase-a1-admin-access.md).
ADMIN_NOT_FOUND = "We couldn’t find that admin."
CLIENT_EMAIL = (
    "This email address belongs to a client account. Please use a different email address."
)
EMAIL_LOCKED = (
    "The email address can’t be changed. To use a different one, deactivate this admin and "
    "invite them again with the new address."
)

# 7.2's Admin Permissions.
PERMISSIONS = AdminPermissions(
    can="Everything in the admin panel, except:",
    cannot=[
        "Admin Management: adding, editing and deactivating Admins",
        "Managing subscription plans and pricing",
        "Seeing subscription and free trial metrics on the Dashboard",
        "Seeing Clients’ subscription details",
        "Approving and publishing, or rejecting, knowledge base content (what Admins add or "
        "edit goes to the Super Admin for approval)",
        "Consent Management, and viewing the Audit Logs",
    ],
)


def _now() -> datetime:
    return datetime.now(UTC)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Reading


def _last_active():
    return (
        select(func.max(UserSession.last_seen_at))
        .where(UserSession.user_id == AdminInvitation.user_id)
        .correlate(AdminInvitation)
        .scalar_subquery()
    )


def _columns(now: datetime):
    first = func.coalesce(User.first_name, AdminInvitation.first_name)
    last = func.coalesce(User.last_name, AdminInvitation.last_name)
    email = func.coalesce(User.email, AdminInvitation.email)
    status = case(
        (
            AdminInvitation.user_id.is_(None) & (AdminInvitation.expires_at > now),
            "invite_pending",
        ),
        (AdminInvitation.user_id.is_(None), "invite_expired"),
        (User.status == "active", "active"),
        else_="deactivated",
    )
    return first, last, email, status


def _status(invitation: AdminInvitation, user: User | None) -> AdminStatus:
    if user is None:
        return "invite_pending" if invitation.expires_at > _now() else "invite_expired"
    return "active" if user.status == "active" else "deactivated"


def _summary(
    invitation: AdminInvitation, user: User | None, last_active: datetime | None
) -> AdminSummary:
    return AdminSummary(
        id=invitation.id,
        user_id=invitation.user_id,
        first_name=user.first_name if user else invitation.first_name,
        last_name=(user.last_name or "") if user else invitation.last_name,
        email=user.email if user else invitation.email,
        status=_status(invitation, user),
        added_at=invitation.created_at,
        last_active_at=last_active,
    )


def list_admins(
    db: Session, search: str | None, status: AdminStatus | None, limit: int, offset: int
) -> AdminPage:
    """7.1's listing: every Admin that isn't a cancelled invite, newest first, searched by name
    or email and filtered by status. The Super Admin isn't listed."""
    now = _now()
    first, last, email, status_column = _columns(now)
    conditions = [AdminInvitation.cancelled_at.is_(None)]
    term = (search or "").strip()
    if term:
        pattern = _like(term)
        conditions.append(
            or_(
                first.ilike(pattern),
                last.ilike(pattern),
                email.ilike(pattern),
                (first + " " + last).ilike(pattern),
            )
        )
    if status is not None:
        conditions.append(status_column == status)
    base = (
        select(AdminInvitation, User, _last_active())
        .outerjoin(User, User.id == AdminInvitation.user_id)
        .where(*conditions)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(AdminInvitation.created_at.desc(), AdminInvitation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [_summary(invitation, user, last_active) for invitation, user, last_active in rows]
    filtered = bool(term) or status is not None
    return AdminPage(
        items=items, total=total, message=NO_RESULTS if not items and filtered else None
    )


def _find(db: Session, admin_id: uuid.UUID, *, lock: bool = False) -> AdminInvitation:
    stmt = select(AdminInvitation).where(AdminInvitation.id == admin_id)
    if lock:
        stmt = stmt.with_for_update()
    invitation = db.scalar(stmt)
    if invitation is None or invitation.cancelled_at is not None:
        raise AppError(404, "admin_not_found", ADMIN_NOT_FOUND)
    return invitation


def _deactivation(db: Session, user: User) -> tuple[datetime | None, str | None]:
    """When and why the account was last deactivated: the reason is kept with the audit event,
    as Super Admin 3.2 does for clients."""
    row = db.execute(
        select(AuditEvent.occurred_at, AuditEvent.details)
        .where(
            AuditEvent.action == "admin.deactivated",
            AuditEvent.target_type == "user",
            AuditEvent.target_id == str(user.id),
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return row.occurred_at, (row.details or {}).get("reason")


def _details(db: Session, invitation: AdminInvitation) -> AdminDetails:
    user = invitation.user
    last_active = (
        db.scalar(select(func.max(UserSession.last_seen_at)).where(UserSession.user_id == user.id))
        if user
        else None
    )
    summary = _summary(invitation, user, last_active)
    inviter = invitation.invited_by
    added_by = (
        " ".join(part for part in (inviter.first_name, inviter.last_name) if part)
        if inviter
        else None
    )
    deactivated_at = reason = None
    if summary.status == "deactivated":
        deactivated_at, reason = _deactivation(db, user)
    actions = {
        "invite_pending": ["edit", "resend_invite", "cancel_invite"],
        "invite_expired": ["edit", "resend_invite", "cancel_invite"],
        "active": ["edit", "deactivate"],
        "deactivated": ["edit", "reactivate"],
    }[summary.status]
    confirmation = (
        f"Deactivate {summary.first_name}? They’ll be signed out and won’t be able to sign in "
        "until they’re reactivated."
        if "deactivate" in actions
        else None
    )
    return AdminDetails(
        **summary.model_dump(),
        added_by=added_by,
        invite_expires_at=invitation.expires_at if user is None else None,
        deactivated_at=deactivated_at,
        deactivation_reason=reason,
        permissions=PERMISSIONS,
        actions=actions,
        deactivate_confirmation=confirmation,
    )


def get_admin(db: Session, admin_id: uuid.UUID) -> AdminDetails:
    """7.1's Admin Details."""
    return _details(db, _find(db, admin_id))


# Inviting (7.2) and pending invites (7.1)


def _issue_link(invitation: AdminInvitation, now: datetime) -> str:
    """A new link for the invite; any earlier link stops working, and setup starts again."""
    token = new_token()
    invitation.token_hash = hash_secret(token)
    invitation.expires_at = now + timedelta(hours=settings.admin_invite_hours)
    invitation.sent_at = now
    invitation.password_hash = None
    invitation.code_hash = None
    invitation.code_sent_at = None
    invitation.code_expires_at = None
    invitation.code_attempts = 0
    invitation.code_send_count = 0
    return token


def _refuse_used_email(db: Session, email: str) -> None:
    """7.2: the email mustn't be used by an Admin or the Super Admin, including one invited and
    not set up yet. users.email is unique, so a client's email can't be used either."""
    role = db.scalar(select(User.role).where(User.email == email))
    if role is not None:
        message = ADMIN_EXISTS if role in ADMIN_ROLES else CLIENT_EMAIL
        raise AppError(409, "email_taken", message, "email")
    open_invite = db.scalar(
        select(AdminInvitation.id).where(
            AdminInvitation.email == email,
            AdminInvitation.accepted_at.is_(None),
            AdminInvitation.cancelled_at.is_(None),
        )
    )
    if open_invite is not None:
        raise AppError(409, "email_taken", ADMIN_EXISTS, "email")


def invite_admin(
    db: Session, send: SendEmail, super_admin: User, data: InviteAdminIn, request: Request
) -> tuple[str, AdminDetails]:
    """7.2's Send invite: the Admin appears as Invite pending, and gets the Set up your account
    link, valid 24 hours."""
    now = _now()
    try:
        _refuse_used_email(db, data.email)
        invitation = AdminInvitation(
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            invited_by_id=super_admin.id,
            token_hash="",
            expires_at=now,
            sent_at=now,
        )
        token = _issue_link(invitation, now)
        db.add(invitation)
        try:
            db.flush()
        except IntegrityError:  # the same email was invited at the same moment
            db.rollback()
            raise AppError(409, "email_taken", ADMIN_EXISTS, "email") from None
        audit.record(
            db,
            "admin.invited",
            actor_id=super_admin.id,
            target_type="admin_invitation",
            target_id=invitation.id,
            request=request,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "send_failed", SEND_FAILED) from None
    send(emails.invite(invitation.email, invitation.first_name, token))
    message = (
        f"We’ve sent an invite to {invitation.email}. "
        f"It’s valid for {settings.admin_invite_hours} hours."
    )
    return message, _details(db, invitation)


def _open_invite(db: Session, admin_id: uuid.UUID) -> AdminInvitation:
    invitation = _find(db, admin_id, lock=True)
    if invitation.accepted_at is not None:
        raise AppError(
            409,
            "already_set_up",
            f"{invitation.first_name} has already set up their account.",
        )
    return invitation


def resend_invite(
    db: Session, send: SendEmail, super_admin: User, admin_id: uuid.UUID, request: Request
) -> tuple[str, AdminDetails]:
    """7.1's Resend invite, also for an expired one: a new email with a new link, valid 24
    hours from now; the old link stops working."""
    try:
        invitation = _open_invite(db, admin_id)
        token = _issue_link(invitation, _now())
        invitation.send_count += 1
        audit.record(
            db,
            "admin.invite_resent",
            actor_id=super_admin.id,
            target_type="admin_invitation",
            target_id=invitation.id,
            request=request,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "send_failed", SEND_FAILED) from None
    send(emails.invite(invitation.email, invitation.first_name, token))
    return f"We’ve sent {invitation.first_name} a new invite.", _details(db, invitation)


def cancel_invite(db: Session, super_admin: User, admin_id: uuid.UUID, request: Request) -> str:
    """7.1's Cancel invite: the link stops working, and the Admin leaves the listing."""
    with database_errors_retryable(db):
        invitation = _open_invite(db, admin_id)
        invitation.cancelled_at = _now()
        invitation.cancelled_by_id = super_admin.id
        invitation.password_hash = None
        invitation.code_hash = None
        audit.record(
            db,
            "admin.invite_cancelled",
            actor_id=super_admin.id,
            target_type="admin_invitation",
            target_id=invitation.id,
            request=request,
        )
        db.commit()
    return f"The invite for {invitation.first_name} has been cancelled."


# Editing, deactivating and reactivating (7.1)


def edit_admin(
    db: Session, super_admin: User, admin_id: uuid.UUID, data: EditAdminIn, request: Request
) -> tuple[str, AdminDetails]:
    """7.1's Edit: the first and last name. The email is used to sign in, so it can't change."""
    with database_errors_retryable(db):
        invitation = _find(db, admin_id, lock=True)
        user = invitation.user
        current_email = user.email if user else invitation.email
        # Sent unchanged is fine (the panel may send the whole form); anything else isn't.
        if data.email is not None and data.email.strip().lower() != current_email:
            raise AppError(422, "email_locked", EMAIL_LOCKED, "email")
        if user is not None:
            db.refresh(user, with_for_update=True)
            record = user
        else:
            record = invitation
        changed = [
            field
            for field in ("first_name", "last_name")
            if getattr(record, field) != getattr(data, field)
        ]
        for field in changed:
            setattr(record, field, getattr(data, field))
        if changed:
            audit.record(
                db,
                "admin.edited",
                actor_id=super_admin.id,
                target_type="user" if user else "admin_invitation",
                target_id=user.id if user else invitation.id,
                request=request,
                details={"fields": changed},
            )
        db.commit()
    return f"{data.first_name}’s details have been updated.", _details(db, invitation)


def _set_up_account(db: Session, admin_id: uuid.UUID) -> tuple[AdminInvitation, User]:
    invitation = _find(db, admin_id)
    user = invitation.user
    if user is None:
        raise AppError(
            409,
            "not_set_up",
            f"{invitation.first_name} hasn’t set up their account yet. You can cancel the "
            "invite instead.",
        )
    db.refresh(user, with_for_update=True)
    return invitation, user


def deactivate_admin(
    db: Session,
    super_admin: User,
    admin_id: uuid.UUID,
    data: DeactivateAdminIn,
    request: Request,
) -> tuple[str, AdminDetails]:
    """7.1's Deactivate, with a reason: the Admin is signed out straight away on every device
    and can't sign in; nothing they did is changed."""
    now = _now()
    with database_errors_retryable(db):
        invitation, user = _set_up_account(db, admin_id)
        if user.status != "active":
            raise AppError(409, "already_deactivated", f"{user.first_name} is already deactivated.")
        user.status = "deactivated"
        # Their sessions end now, and keep the deactivated message on every later request.
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason="account_deactivated")
        )
        # Open codes and reset links close, so none can be used meanwhile.
        db.execute(
            update(VerificationChallenge)
            .where(
                VerificationChallenge.user_id == user.id, VerificationChallenge.used_at.is_(None)
            )
            .values(used_at=now)
        )
        db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        db.execute(delete(TrustedDevice).where(TrustedDevice.user_id == user.id))
        audit.record(
            db,
            "admin.deactivated",
            actor_id=super_admin.id,
            target_type="user",
            target_id=user.id,
            request=request,
            details={"reason": data.reason},
        )
        db.commit()
    return f"{user.first_name} has been deactivated.", _details(db, invitation)


def reactivate_admin(
    db: Session, super_admin: User, admin_id: uuid.UUID, request: Request
) -> tuple[str, AdminDetails]:
    """7.1's Reactivate: the Admin signs in again with their password and a new code."""
    with database_errors_retryable(db):
        invitation, user = _set_up_account(db, admin_id)
        if user.status == "active":
            raise AppError(409, "already_active", f"{user.first_name} is already active.")
        user.status = "active"
        user.failed_sign_ins = 0
        user.locked_until = None
        audit.record(
            db,
            "admin.reactivated",
            actor_id=super_admin.id,
            target_type="user",
            target_id=user.id,
            request=request,
        )
        db.commit()
    return f"{user.first_name} has been reactivated.", _details(db, invitation)
