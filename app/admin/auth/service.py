"""An invited Admin's account setup (Admin 1.1, Super Admin 7.2).

1. `check_invitation`: the setup screen reads the invite (name and email, locked).
2. `accept_invitation`: the Admin sets a password; a 6-digit code is emailed to the invite's
   address.
3. `verify_setup_code`: the right code creates the account (role `admin`), marks the invite
   used, and tells the Super Admin. The Admin then signs in as usual, with a new code.

The invite row is locked (FOR UPDATE) in every step that changes it. Codes follow the sign-in
rules: valid 10 minutes, 5 tries, resend after 60 seconds, at most 5 per invite. Wrong and
refused codes are recorded as `auth.code.failed` and `auth.code.rejected`, so the per-IP limit
on `/auth/verify` counts them too.
"""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin.auth import emails
from app.admin.auth.models import AdminInvitation
from app.admin.auth.schemas import (
    AcceptInvitationRequest,
    InvitationOut,
    SetupCodeRequest,
    SetupCodeSent,
)
from app.admin.notifications.service import notify_admins
from app.auth import service as auth
from app.auth.models import User
from app.auth.security import hash_password, hash_secret, new_code, secret_matches
from app.core import audit
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import AppError

# Admin 1.1's and Super Admin 7.2's messages.
INVITE_EXPIRED = "This invite has expired. Please ask the Super Admin to send a new one."
ACCOUNT_READY = "Your account is ready. Please sign in."
CODE_WRONG = auth.CODE_WRONG["sign_in"]  # Admin 1.1 uses 1.2's code messages
CODE_EXPIRED = auth.CODE_EXPIRED["sign_in"]
# Not in the stories (docs/decisions/phase-a1-admin-access.md).
EMAIL_IN_USE = (
    "An account with this email address already exists. Please ask the Super Admin to send a "
    "new invite."
)
SET_PASSWORD_FIRST = "Please set your password first."
RESEND_TOO_SOON = "Please wait a minute before asking for a new code."
TOO_MANY_SETUP_CODES = (
    "You’ve asked for too many codes. Please ask the Super Admin to send a new invite."
)

REJECTED = "admin.invite_rejected"  # a bad, used, cancelled or expired invite token


def _now() -> datetime:
    return datetime.now(UTC)


def usable(invitation: AdminInvitation) -> bool:
    """Not set up, not cancelled and not expired (Admin 1.1: "Expired or used link")."""
    return (
        invitation.accepted_at is None
        and invitation.cancelled_at is None
        and invitation.expires_at > _now()
    )


def _closed_reason(invitation: AdminInvitation | None) -> str:
    if invitation is None:
        return "unknown"
    if invitation.accepted_at is not None:
        return "used"
    if invitation.cancelled_at is not None:
        return "cancelled"
    return "expired"


def _open_invitation(
    db: Session, request: Request, token: str, *, lock: bool = True
) -> AdminInvitation:
    """The invite for this link, locked, or Admin 1.1's expired message. One message for an
    unknown, used, cancelled or expired link, as the story has."""
    stmt = select(AdminInvitation).where(AdminInvitation.token_hash == hash_secret(token))
    if lock:
        stmt = stmt.with_for_update()
    invitation = db.scalar(stmt)
    if invitation is None or not usable(invitation):
        audit.record(
            db,
            REJECTED,
            target_type="admin_invitation" if invitation is not None else None,
            target_id=invitation.id if invitation is not None else None,
            request=request,
            details={"reason": _closed_reason(invitation)},
        )
        db.commit()
        raise AppError(400, "invite_expired", INVITE_EXPIRED)
    return invitation


def _email_taken(db: Session, invitation: AdminInvitation) -> bool:
    return db.scalar(select(User.id).where(User.email == invitation.email)) is not None


def _code_sent(invitation: AdminInvitation) -> SetupCodeSent:
    waited = int((_now() - invitation.code_sent_at).total_seconds())
    return SetupCodeSent(
        expires_in_seconds=settings.code_ttl_minutes * 60,
        resend_after_seconds=max(0, settings.code_resend_seconds - waited),
    )


def _send_new_code(
    db: Session, send: SendEmail, invitation: AdminInvitation, request: Request, resend: bool
) -> SetupCodeSent:
    """A new code with 5 new tries; the old one stops working. Commits, then emails it."""
    if invitation.code_send_count >= settings.code_max_sends:
        db.commit()  # keeps a new password the caller set
        raise AppError(429, "too_many_codes", TOO_MANY_SETUP_CODES)
    now = _now()
    code = new_code()
    invitation.code_hash = hash_secret(code)
    invitation.code_sent_at = now
    invitation.code_expires_at = now + timedelta(minutes=settings.code_ttl_minutes)
    invitation.code_attempts = 0
    invitation.code_send_count += 1
    audit.record(
        db,
        "auth.code.sent",
        actor_id=invitation.id,
        request=request,
        details={"purpose": "admin_setup", "resend": resend},
    )
    db.commit()
    send(emails.setup_code(invitation.email, code))
    return _code_sent(invitation)


def check_invitation(db: Session, token: str, request: Request) -> InvitationOut:
    """Admin 1.1's "Valid link": the setup screen, with the name and email from the invite."""
    auth.check_ip_limit(db, request, REJECTED)
    invitation = _open_invitation(db, request, token, lock=False)
    return InvitationOut(
        first_name=invitation.first_name,
        last_name=invitation.last_name,
        email=invitation.email,
        expires_at=invitation.expires_at,
    )


def accept_invitation(
    db: Session, send: SendEmail, data: AcceptInvitationRequest, request: Request
) -> SetupCodeSent:
    """Admin 1.1, Set up account: keeps the password (hashed) and emails a code to confirm the
    address. The link can be used again until the code is verified (the Admin may close the
    page), and doing so replaces the password and sends a new code."""
    auth.check_ip_limit(db, request, REJECTED)
    auth.check_ip_limit(db, request, "auth.code.sent")
    invitation = _open_invitation(db, request, data.token)
    if _email_taken(db, invitation):
        # Someone signed up as a client with this address after the invite was sent.
        audit.record(
            db,
            REJECTED,
            target_type="admin_invitation",
            target_id=invitation.id,
            request=request,
            details={"reason": "email_taken"},
        )
        db.commit()
        raise AppError(409, "email_taken", EMAIL_IN_USE)
    invitation.password_hash = hash_password(data.password)
    audit.record(
        db,
        "admin.invite_accepted",
        target_type="admin_invitation",
        target_id=invitation.id,
        request=request,
    )
    if invitation.code_sent_at is not None and _now() - invitation.code_sent_at < timedelta(
        seconds=settings.code_resend_seconds
    ):
        # Sent again straight away (a double click): the code already sent still works.
        db.commit()
        return _code_sent(invitation)
    return _send_new_code(db, send, invitation, request, resend=False)


def resend_setup_code(db: Session, send: SendEmail, token: str, request: Request) -> SetupCodeSent:
    """Admin 1.1's "Resend code", after 60 seconds."""
    auth.check_ip_limit(db, request, "auth.code.sent")
    invitation = _open_invitation(db, request, token)
    if invitation.password_hash is None or invitation.code_sent_at is None:
        raise AppError(400, "setup_not_started", SET_PASSWORD_FIRST)
    if _now() - invitation.code_sent_at < timedelta(seconds=settings.code_resend_seconds):
        raise AppError(429, "resend_too_soon", RESEND_TOO_SOON)
    return _send_new_code(db, send, invitation, request, resend=True)


def _refuse_code(db: Session, request: Request, invitation: AdminInvitation, reason: str) -> None:
    audit.record(
        db,
        "auth.code.rejected",
        target_type="admin_invitation",
        target_id=invitation.id,
        request=request,
        details={"reason": reason, "purpose": "admin_setup"},
    )
    db.commit()
    raise AppError(400, "code_expired", CODE_EXPIRED, "code")


def verify_setup_code(db: Session, data: SetupCodeRequest, request: Request) -> str:
    """Admin 1.1's Verification: the right code creates the Admin's account and tells the
    Super Admin (Super Admin 11.1). Returns "Your account is ready. Please sign in."."""
    auth.check_ip_limit(db, request, "auth.code.failed", "auth.code.rejected")
    invitation = _open_invitation(db, request, data.token)
    now = _now()
    if invitation.code_hash is None or invitation.password_hash is None:
        _refuse_code(db, request, invitation, "no_code")
    if invitation.code_expires_at <= now:
        _refuse_code(db, request, invitation, "expired")
    if invitation.code_attempts >= settings.code_max_attempts:
        _refuse_code(db, request, invitation, "too_many_attempts")

    if not secret_matches(data.code, invitation.code_hash):
        invitation.code_attempts += 1
        audit.record(
            db,
            "auth.code.failed",
            actor_id=invitation.id,
            request=request,
            details={"reason": "wrong", "purpose": "admin_setup"},
        )
        db.commit()
        if invitation.code_attempts >= settings.code_max_attempts:
            raise AppError(400, "code_expired", CODE_EXPIRED, "code")  # only a new code helps
        raise AppError(400, "code_wrong", CODE_WRONG, "code")

    user = User(
        role="admin",
        email=invitation.email,
        first_name=invitation.first_name,
        last_name=invitation.last_name,
        password_hash=invitation.password_hash,
        email_verified_at=now,
        trial_ends_at=now,  # required for every account; admins have no trial
        password_changed_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # an account with this email appeared meanwhile
        db.rollback()
        raise AppError(409, "email_taken", EMAIL_IN_USE) from None
    invitation.user_id = user.id
    invitation.accepted_at = now
    invitation.password_hash = None
    invitation.code_hash = None
    invitation.code_expires_at = None
    audit.record(
        db,
        "admin.set_up",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
        details={"admin_invitation_id": str(invitation.id)},
    )
    audit.record(db, "auth.email_verified", actor_id=user.id, request=request)
    notify_admins(db, "admin_set_up", {"name": user.first_name}, target_id=invitation.id)
    db.commit()
    return ACCOUNT_READY
