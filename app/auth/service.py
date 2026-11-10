"""Sign-up, sign-in, verification codes, sessions and passwords (stories 1.1–1.4 and 12.2).

Rows whose counters or single-use state change (users at sign-in, challenges, reset tokens)
are loaded with SELECT ... FOR UPDATE, so parallel requests can't each read the old value.

Admins and the Super Admin (Phase A) use the same flows, with their stories' rules
(Super Admin 1.1 and 1.2, Admin 1.2 and 1.3): a code at every sign-in on every device (no
trusted devices), always a web session, their own deactivated and "not set up" messages, and
the admin panel's emails. The 15-minute inactivity timeout is in app/auth/dependencies.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.accounts.models import PolicyVersion
from app.admin.auth import emails as admin_emails
from app.admin.auth.models import AdminInvitation
from app.auth import emails
from app.auth.models import (
    PasswordResetToken,
    PendingSignUp,
    TrustedDevice,
    User,
    UserSession,
    VerificationChallenge,
)
from app.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    Platform,
    ResendCodeRequest,
    ResetPasswordRequest,
    SignedIn,
    SignInRequest,
    SignOutRequest,
    SignUpDetails,
    SignUpRequest,
    VerificationRequired,
    VerifyRequest,
)
from app.auth.security import (
    hash_password,
    hash_secret,
    new_code,
    new_token,
    secret_matches,
    verify_password,
)
from app.billing import catalog
from app.core import audit, jobs
from app.core.ages import is_adult
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.email import EmailMessage, SendEmail
from app.core.errors import ACTION_FAILED, AppError

PURGE_PENDING_SIGN_UP_JOB = "auth.purge_pending_sign_up"  # see app/auth/jobs.py

# Wording from the stories, or chosen in docs/PLAN.md where the stories conflict.
INVALID_CREDENTIALS = "Incorrect email or password. Please try again."
ACCOUNT_LOCKED = (
    "Your account has been temporarily locked after too many attempts. "
    "Please reset your password to continue."
)
ACCOUNT_DEACTIVATED = "Your account has been deactivated. Please contact the support team for help."
# Admin 1.2 (an Admin is deactivated by the Super Admin, Super Admin 7.1).
ADMIN_DEACTIVATED = "Your account has been deactivated. Please contact the Super Admin."
ACCOUNT_NOT_SET_UP = "Please set up your account using the link in your invite email."
EMAIL_TAKEN = "An account with this email already exists. Please sign in."
UNDER_AGE = "Please ask a parent or guardian to add you as a family member."
# Stories 1.1 and 1.2 word the code messages differently; each purpose uses its own story's.
CODE_WRONG = {
    "verify_email": "That code isn’t right. Please try again.",
    "sign_in": "That code doesn’t match. Please check your email and try again.",
}
CODE_EXPIRED = {
    "verify_email": "Please request a new code.",
    "sign_in": "This code has expired. Please request a new one.",
}
TOO_MANY_CODES = "You’ve asked for too many codes. Please wait an hour and try again."
# Not in the stories: a challenge that can't send more codes (docs/PLAN.md, R1).
RESEND_LIMIT = {
    "verify_email": "Please sign up again to get a new code.",
    "sign_in": "Please sign in again to get a new code.",
}
RESET_LINK_EXPIRED = "This link has expired. Please request a new one."
PASSWORD_REUSED = "Please choose a password you haven’t used before."
SIGNED_OUT = "You’ve been signed out. Please sign in again to continue."
TOO_MANY_ATTEMPTS = "Too many attempts. Please wait a few minutes and try again."
CHANGE_PASSWORD_FAILED = "We couldn’t change your password just now. Please try again."

# A lock that only a password reset ends (reset_password clears locked_until).
LOCKED_UNTIL_RESET = datetime(9999, 12, 31, tzinfo=UTC)

# The roles that use the admin panel (users.role; clients are "client").
ADMIN_ROLES = frozenset({"admin", "super_admin"})


def _now() -> datetime:
    return datetime.now(UTC)


def _ip(request: Request) -> str | None:
    return audit.client_ip(request)  # the same form the audit log stores, so counts match


def is_admin(user: User) -> bool:
    """An Admin or the Super Admin: they sign in with a code every time (Super Admin 1.1)."""
    return user.role in ADMIN_ROLES


def deactivated_message(role: str) -> str:
    """Client 1.2 points a deactivated client to the support team; Admin 1.2 points a
    deactivated Admin to the Super Admin."""
    return ADMIN_DEACTIVATED if role in ADMIN_ROLES else ACCOUNT_DEACTIVATED


def _invite_pending(db: Session, email: str) -> bool:
    """Admin 1.2's "Account not set up": an invite for this email that hasn't been set up or
    cancelled. Expired ones count, so the Admin is told to use (or renew) the invite."""
    return (
        db.scalar(
            select(AdminInvitation.id).where(
                AdminInvitation.email == email,
                AdminInvitation.accepted_at.is_(None),
                AdminInvitation.cancelled_at.is_(None),
            )
        )
        is not None
    )


def _count_events(
    db: Session,
    actions: str | tuple[str, ...],
    within: timedelta,
    *,
    ip: str | None = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> int:
    """Counts recent audit events: those in the last `within`, and after `since` if given."""
    if isinstance(actions, str):
        actions = (actions,)
    start = _now() - within
    if since is not None and since > start:
        start = since
    stmt = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action.in_(actions), AuditEvent.occurred_at > start)
    )
    if ip is not None:
        stmt = stmt.where(AuditEvent.ip_address == ip)
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    return db.scalar(stmt)


def _check_ip_limit(db: Session, request: Request, *actions: str) -> None:
    """Refuses an IP address with too many recent events of these kinds across all accounts.
    This is a coarse limit; the per-account limits below do the real work."""
    ip = _ip(request)
    if ip is None:
        # Only possible behind a proxy that hides the client (uvicorn on a socket, say).
        # Every per-IP limit would be skipped, so production refuses instead.
        if settings.environment == "production":
            raise AppError(503, "save_failed", ACTION_FAILED)
        return
    window = timedelta(minutes=settings.ip_failure_window_minutes)
    if _count_events(db, actions, window, ip=ip) >= settings.ip_failure_limit:
        audit.record(
            db, "auth.rate_limited", request=request, details={"limited_action": actions[0]}
        )
        db.commit()
        raise AppError(429, "too_many_attempts", TOO_MANY_ATTEMPTS)


def check_ip_limit(db: Session, request: Request, *actions: str) -> None:
    """The per-IP limit, for other flows with a secret to guess (the admin invite's setup)."""
    _check_ip_limit(db, request, *actions)


def _lock_account(
    db: Session, user: User, request: Request, reason: str, until_reset: bool = False
) -> None:
    if until_reset:
        user.locked_until = LOCKED_UNTIL_RESET
    else:
        user.locked_until = _now() + timedelta(minutes=settings.lockout_minutes)
    audit.record(
        db,
        "auth.account_locked",
        actor_id=user.id,
        request=request,
        details={"reason": reason, "until_reset": until_reset},
    )


def _platform(declared: Platform, request: Request) -> Platform:
    """The platform a new session gets (story 1.2: web sessions time out sooner).

    The mobile app says "mobile" when it signs in. Browsers add Origin or Sec-Fetch-Mode to
    a page's requests, and the page's own code can't remove them, so a browser always gets a
    web session, whatever it claims. Native apps' HTTP clients send neither header."""
    if request.headers.get("origin") or request.headers.get("sec-fetch-mode"):
        return "web"
    return declared


def _close_open_secrets(db: Session, user: User) -> None:
    """Closes the user's open codes and reset links. Called whenever the password changes."""
    now = _now()
    db.execute(
        update(VerificationChallenge)
        .where(VerificationChallenge.user_id == user.id, VerificationChallenge.used_at.is_(None))
        .values(used_at=now)
    )
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )


# Verification codes


def _codes_sent_last_hour(db: Session, owner_id: uuid.UUID) -> int:
    return _count_events(db, "auth.code.sent", timedelta(hours=1), actor_id=owner_id)


def _send_code(
    db: Session,
    send: SendEmail,
    owner: User | PendingSignUp,
    purpose: str,
    request: Request,
) -> VerificationRequired:
    """Starts a new challenge for an account (sign-in) or a pending sign-up (closing any open
    one), commits, and emails the code. Either way the owner's id is the audit actor that the
    limits count: a pending sign-up's id becomes its account's id."""
    if _codes_sent_last_hour(db, owner.id) >= settings.max_codes_sent_per_hour:
        audit.record(
            db,
            "auth.code.limited",
            actor_id=owner.id,
            request=request,
            details={"purpose": purpose},
        )
        db.commit()  # also keeps what the caller changed, such as the reset failure count
        raise AppError(429, "too_many_codes", TOO_MANY_CODES)

    now = _now()
    is_account = isinstance(owner, User)
    owner_column = (
        VerificationChallenge.user_id if is_account else VerificationChallenge.pending_sign_up_id
    )
    db.execute(
        update(VerificationChallenge)
        .where(owner_column == owner.id, VerificationChallenge.used_at.is_(None))
        .values(used_at=now)
    )
    code = new_code()
    challenge = VerificationChallenge(
        user_id=owner.id if is_account else None,
        pending_sign_up_id=None if is_account else owner.id,
        purpose=purpose,
        code_hash=hash_secret(code),
        sent_at=now,
        expires_at=now + timedelta(minutes=settings.code_ttl_minutes),
    )
    db.add(challenge)
    audit.record(
        db, "auth.code.sent", actor_id=owner.id, request=request, details={"purpose": purpose}
    )
    db.commit()
    send(_code_email(owner, code, purpose))
    return _verification_required(challenge)


def _code_email(owner: User | PendingSignUp, code: str, purpose: str) -> EmailMessage:
    """Admins get the admin panel's wording: their code comes at every sign-in, not only on a
    new device."""
    if isinstance(owner, User) and is_admin(owner):
        return admin_emails.sign_in_code(owner.email, code)
    return emails.verification_code(owner.email, code, purpose)


def _password_reset_email(user: User, token: str) -> EmailMessage:
    """Admins' reset links open the admin panel (Super Admin 1.2, Admin 1.3)."""
    if is_admin(user):
        return admin_emails.password_reset(user.email, token)
    return emails.password_reset(user.email, token)


def _password_changed_email(user: User) -> EmailMessage:
    if is_admin(user):
        return admin_emails.password_changed(user.email)
    return emails.password_changed(user.email)


def _verification_required(challenge: VerificationChallenge) -> VerificationRequired:
    waited = int((_now() - challenge.sent_at).total_seconds())
    return VerificationRequired(
        challenge_id=challenge.id,
        purpose=challenge.purpose,
        expires_in_seconds=settings.code_ttl_minutes * 60,
        resend_after_seconds=max(0, settings.code_resend_seconds - waited),
    )


# Sessions and trusted devices


def _create_session(
    db: Session,
    user: User,
    device: TrustedDevice | None,
    platform: Platform,
    request: Request,
) -> str:
    """Story 1.2: a web session lasts 12 hours at most; a mobile one up to 30 days, but never
    longer than the device stays trusted."""
    now = _now()
    if platform == "mobile":
        expires_at = now + timedelta(days=settings.mobile_session_max_days)
        if device is not None:
            expires_at = min(expires_at, device.expires_at)
    else:
        expires_at = now + timedelta(hours=settings.web_session_max_hours)
    token = new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_secret(token),
            trusted_device_id=device.id if device else None,
            platform=platform,
            ip_address=_ip(request),
            user_agent=request.headers.get("user-agent"),
            last_seen_at=now,
            expires_at=expires_at,
        )
    )
    return token


def _trusted_device(db: Session, user: User, device_token: str | None) -> TrustedDevice | None:
    if not device_token:
        return None
    device = db.scalar(
        select(TrustedDevice).where(
            TrustedDevice.token_hash == hash_secret(device_token),
            TrustedDevice.user_id == user.id,
        )
    )
    if device is None or device.expires_at <= _now():
        return None
    return device


def _revoke_sessions(db: Session, user: User, keep: UserSession | None = None) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep.id)
    db.execute(stmt.values(revoked_at=_now()))


def _forget_devices(db: Session, user: User, keep_id: uuid.UUID | None = None) -> None:
    """After this, the next sign-in on those devices needs 2FA again."""
    stmt = delete(TrustedDevice).where(TrustedDevice.user_id == user.id)
    if keep_id is not None:
        stmt = stmt.where(TrustedDevice.id != keep_id)
    db.execute(stmt)


# Story 1.1: sign up


def check_age(data: SignUpDetails) -> None:
    """Story 1.1: below the age of majority, sign-up stops and nothing is saved. A teen joins
    through a parent's invite instead (story 1.5)."""
    if not is_adult(data.date_of_birth):
        raise AppError(422, "under_age", UNDER_AGE, "date_of_birth")


def sign_up(
    db: Session, send: SendEmail, data: SignUpRequest, request: Request
) -> VerificationRequired:
    """Story 1.1: checks the form and emails a code. No account exists until the code is
    verified (`verify`); until then the details wait in a PendingSignUp, which is deleted if
    the code never is.

    Every sign-up is a separate attempt with its own code, even for the same email: only the
    code emailed to the address makes an account, and someone typing another person's email
    can't close, lock or use up that person's own attempt."""
    # Refusals count too, so the "already exists" message can't be used to test emails in bulk.
    _check_ip_limit(db, request, "auth.sign_up.started", "auth.sign_up.refused")
    check_age(data)
    existing = db.scalar(select(User.id).where(User.email == data.email))
    if existing is not None:
        audit.record(
            db,
            "auth.sign_up.refused",
            target_type="user",
            target_id=existing,
            request=request,
            details={"reason": "email_taken"},
        )
        db.commit()
        raise AppError(409, "email_taken", EMAIL_TAKEN, "email")

    now = _now()
    ip = _ip(request)
    # Code emails to one address from one place, so nobody can flood an inbox. Counted per
    # IP, so it can't be used to stop the owner signing up from their own device. The lock
    # (until commit) makes parallel sign-ups for one email from one place count one by one.
    db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"signup:{data.email}|{ip}", 0)))
    )
    recent = db.scalar(
        select(func.count())
        .select_from(PendingSignUp)
        .where(
            PendingSignUp.email == data.email,
            PendingSignUp.ip_address == ip,
            PendingSignUp.created_at > now - timedelta(hours=1),
        )
    )
    if ip is not None and recent >= settings.max_sign_ups_per_email_per_hour:
        audit.record(db, "auth.code.limited", request=request, details={"purpose": "verify_email"})
        db.commit()
        raise AppError(429, "too_many_codes", TOO_MANY_CODES)

    pending = PendingSignUp(
        email=data.email,
        ip_address=ip,
        first_name=data.first_name,
        date_of_birth=data.date_of_birth,
        country=data.country,
        state=data.state,
        zip_code=data.zip_code,
        password_hash=hash_password(data.password),
        policy_version_ids=[policy.id for policy in accounts.current_policies(db)],
        expires_at=now + timedelta(minutes=settings.pending_sign_up_minutes),
    )
    db.add(pending)
    db.flush()
    audit.record(db, "auth.sign_up.started", actor_id=pending.id, request=request)
    jobs.enqueue(
        db,
        PURGE_PENDING_SIGN_UP_JOB,
        {"pending_sign_up_id": str(pending.id)},
        run_at=pending.expires_at,
    )
    return _send_code(db, send, pending, "verify_email", request)


# Story 1.2: sign in


def sign_in(
    db: Session, send: SendEmail, data: SignInRequest, request: Request
) -> SignedIn | VerificationRequired:
    _check_ip_limit(db, request, "auth.sign_in.failed")
    now = _now()

    # FOR UPDATE makes sign-ins to one account run one at a time, so parallel wrong
    # passwords can't all read the same failure count.
    user = db.scalar(select(User).where(User.email == data.email).with_for_update())
    if user is None:
        verify_password(data.password, None)  # same timing as a wrong password
        if _invite_pending(db, data.email):
            # Admin 1.2: an invited Admin who hasn't set up their account (no password yet) is
            # sent back to the invite. Counted like a failed sign-in by the per-IP limit.
            audit.record(
                db, "auth.sign_in.failed", request=request, details={"reason": "not_set_up"}
            )
            db.commit()
            raise AppError(403, "account_not_set_up", ACCOUNT_NOT_SET_UP)
        audit.record(
            db, "auth.sign_in.failed", request=request, details={"reason": "unknown_email"}
        )
        db.commit()
        raise AppError(401, "invalid_credentials", INVALID_CREDENTIALS)

    if user.locked_until is not None:
        if user.locked_until > now:
            audit.record(
                db,
                "auth.sign_in.blocked",
                actor_id=user.id,
                request=request,
                details={"reason": "locked"},
            )
            db.commit()
            raise AppError(423, "account_locked", ACCOUNT_LOCKED)
        user.locked_until = None  # the lock has run out
        user.failed_sign_ins = 0

    matches, upgraded_hash = verify_password(data.password, user.password_hash)
    if not matches:
        user.failed_sign_ins += 1
        audit.record(
            db,
            "auth.sign_in.failed",
            actor_id=user.id,
            request=request,
            details={"reason": "wrong_password"},
        )
        if user.failed_sign_ins >= settings.max_failed_sign_ins:
            _lock_account(db, user, request, "wrong_passwords")
            db.commit()
            raise AppError(423, "account_locked", ACCOUNT_LOCKED)
        db.commit()
        raise AppError(401, "invalid_credentials", INVALID_CREDENTIALS)

    # Checked after the password, so only the account owner learns it's deactivated.
    if user.status != "active":
        audit.record(
            db,
            "auth.sign_in.blocked",
            actor_id=user.id,
            request=request,
            details={"reason": "deactivated"},
        )
        db.commit()
        raise AppError(403, "account_deactivated", deactivated_message(user.role))

    user.failed_sign_ins = 0
    if upgraded_hash is not None:
        user.password_hash = upgraded_hash

    if is_admin(user):
        # Super Admin 1.1 and Admin 1.2: a code at every sign-in, on every device, because
        # admins can see clients' information. Their devices are never trusted.
        return _send_code(db, send, user, "sign_in", request)
    device = _trusted_device(db, user, data.device_token)
    if device is None:  # new device, expired trust, or trust cleared by a reset or sign-out
        return _send_code(db, send, user, "sign_in", request)

    device.last_used_at = now
    # The platform the device had when it passed 2FA, not the one claimed now: a web
    # browser's device token can't make a 30-day mobile session.
    platform = _platform(device.platform, request)
    token = _create_session(db, user, device, platform, request)
    audit.record(
        db,
        "auth.sign_in.succeeded",
        actor_id=user.id,
        request=request,
        details={"two_factor": False, "platform": platform},
    )
    db.commit()
    return SignedIn(access_token=token)


def _reject_code(
    db: Session, request: Request, challenge: VerificationChallenge | None, reason: str
) -> None:
    """Records a code refused before it was compared, and commits. The IP limit counts these,
    but the account's code locks don't: an old challenge id must not be a way to push
    someone else's account towards a lock. The account is the target, not the actor."""
    if challenge is None:
        target_type, target_id = None, None
    elif challenge.user_id is not None:
        target_type, target_id = "user", challenge.user_id
    elif challenge.pending_sign_up_id is not None:
        target_type, target_id = "pending_sign_up", challenge.pending_sign_up_id
    else:  # a sign-up's closed code, after the sign-up was deleted
        target_type, target_id = None, None
    audit.record(
        db,
        "auth.code.rejected",
        target_type=target_type,
        target_id=target_id,
        request=request,
        details={"reason": reason},
    )
    db.commit()


def _check_open(db: Session, request: Request, challenge: VerificationChallenge) -> None:
    """Refuses a code that's used, expired, or has had its 5 tries (stories 1.1 and 1.2)."""
    expired = CODE_EXPIRED[challenge.purpose]
    if challenge.used_at is not None or challenge.expires_at <= _now():
        _reject_code(db, request, challenge, "expired")
        raise AppError(400, "code_expired", expired, "code")
    if challenge.attempts >= settings.code_max_attempts:
        _reject_code(db, request, challenge, "too_many_attempts")
        raise AppError(400, "code_expired", expired, "code")


def _sign_in_after_code(db: Session, user: User, declared: Platform, request: Request) -> SignedIn:
    """After a right code: trusts this device for 30 days and starts a session (stories 1.1
    and 1.2). The caller commits.

    An admin's device isn't trusted (Super Admin 1.1: a new code at every sign-in), and the
    session is always a web one: the admin panel is a web app, and a declared "mobile" must
    not get a 30-day session with no idle timeout."""
    if is_admin(user):
        token = _create_session(db, user, None, "web", request)
        audit.record(
            db,
            "auth.sign_in.succeeded",
            actor_id=user.id,
            request=request,
            details={"two_factor": True, "platform": "web"},
        )
        return SignedIn(access_token=token)
    platform = _platform(declared, request)
    device_token = new_token()
    device = TrustedDevice(
        user_id=user.id,
        token_hash=hash_secret(device_token),
        platform=platform,
        expires_at=_now() + timedelta(days=settings.trusted_device_days),
        last_used_at=_now(),
    )
    db.add(device)
    db.flush()
    token = _create_session(db, user, device, platform, request)
    audit.record(
        db,
        "auth.sign_in.succeeded",
        actor_id=user.id,
        request=request,
        details={"two_factor": True, "platform": platform},
    )
    return SignedIn(access_token=token, device_token=device_token)


def verify(db: Session, send: SendEmail, data: VerifyRequest, request: Request) -> SignedIn:
    """Checks a code from sign-up or sign-in. Success signs the client in and trusts the
    device; a sign-up's code also creates the account."""
    _check_ip_limit(db, request, "auth.code.failed", "auth.code.rejected")
    now = _now()

    challenge = db.get(VerificationChallenge, data.challenge_id)
    if challenge is None:
        _reject_code(db, request, None, "unknown_challenge")
        raise AppError(400, "code_expired", CODE_EXPIRED["sign_in"], "code")
    if challenge.pending_sign_up_id is not None:
        return _verify_sign_up(db, send, challenge, data, request)
    if challenge.user_id is None:
        # A sign-up's code whose sign-up was deleted (it expired, or became an account): 1.1's
        # "request a new code", and a resend then says to sign up again.
        _reject_code(db, request, challenge, "expired")
        raise AppError(400, "code_expired", CODE_EXPIRED[challenge.purpose], "code")

    # Locks are always taken owner first (the account here), then their codes and links, as
    # in sign_in, so two requests for one account can't deadlock. Refreshing re-reads both
    # rows under the lock.
    db.refresh(challenge.user, with_for_update=True)
    db.refresh(challenge, with_for_update=True)
    expired = CODE_EXPIRED[challenge.purpose]
    _check_open(db, request, challenge)

    user = challenge.user
    # Checked before the code, so a locked account can't be used to keep guessing.
    if user.locked_until is not None and user.locked_until > now:
        _reject_code(db, request, challenge, "locked")
        raise AppError(423, "account_locked", ACCOUNT_LOCKED)

    if not secret_matches(data.code, challenge.code_hash):
        challenge.attempts += 1
        audit.record(
            db, "auth.code.failed", actor_id=user.id, request=request, details={"reason": "wrong"}
        )
        # Guessing across many challenges. Whoever it is has the password, so a long run of
        # wrong codes locks the account until the password is reset. Wrong codes from before
        # the last reset or change don't count.
        failed = {
            window: _count_events(
                db, "auth.code.failed", window, actor_id=user.id, since=user.password_changed_at
            )
            for window in (timedelta(hours=1), timedelta(days=1))
        }
        if failed[timedelta(days=1)] >= settings.max_failed_codes_per_day:
            challenge.used_at = now
            _lock_account(db, user, request, "wrong_codes", until_reset=True)
            db.commit()
            raise AppError(423, "account_locked", ACCOUNT_LOCKED)
        if failed[timedelta(hours=1)] >= settings.max_failed_codes_per_hour:
            challenge.used_at = now
            _lock_account(db, user, request, "wrong_codes")
            db.commit()
            raise AppError(423, "account_locked", ACCOUNT_LOCKED)
        db.commit()
        if challenge.attempts >= settings.code_max_attempts:
            # That was the last try, so this code is finished: ask for a new one (1.1, 1.2).
            raise AppError(400, "code_expired", expired, "code")
        raise AppError(400, "code_wrong", CODE_WRONG[challenge.purpose], "code")

    if user.status != "active":
        _reject_code(db, request, challenge, "deactivated")
        raise AppError(403, "account_deactivated", deactivated_message(user.role))

    challenge.used_at = now
    signed_in = _sign_in_after_code(db, user, data.platform, request)
    db.commit()
    return signed_in


def _lock_pending(db: Session, challenge: VerificationChallenge) -> PendingSignUp | None:
    """Locks the challenge's pending sign-up, then the challenge (the same order everywhere),
    and re-reads both. None when the sign-up is gone: it expired, or another attempt for
    the same email became the account."""
    pending = None
    if challenge.pending_sign_up_id is not None:
        pending = db.get(
            PendingSignUp,
            challenge.pending_sign_up_id,
            with_for_update=True,
            populate_existing=True,
        )
    db.refresh(challenge, with_for_update=True)
    if challenge.pending_sign_up_id is None:
        return None
    return pending


def _verify_sign_up(
    db: Session,
    send: SendEmail,
    challenge: VerificationChallenge,
    data: VerifyRequest,
    request: Request,
) -> SignedIn:
    """Story 1.1: the right code creates the account (with the attempt's id), starts the
    trial and signs the client in on this device."""
    now = _now()
    pending = _lock_pending(db, challenge)
    if pending is None:
        _reject_code(db, request, challenge, "expired")
        raise AppError(400, "code_expired", CODE_EXPIRED["verify_email"], "code")
    _check_open(db, request, challenge)

    if not secret_matches(data.code, challenge.code_hash):
        # Each attempt allows 5 tries a code and 5 codes; the per-IP limit on wrong codes
        # (checked in verify) bounds guessing across attempts. There's no lock per email:
        # anyone could set it off, and with no account yet the owner couldn't get past it.
        challenge.attempts += 1
        audit.record(
            db,
            "auth.code.failed",
            actor_id=pending.id,
            request=request,
            details={"reason": "wrong"},
        )
        db.commit()
        if challenge.attempts >= settings.code_max_attempts:
            raise AppError(400, "code_expired", CODE_EXPIRED["verify_email"], "code")
        raise AppError(400, "code_wrong", CODE_WRONG["verify_email"], "code")

    user = User(
        id=pending.id,
        # Sign-up only ever makes clients: admins come from an invite (Admin 1.1) and the
        # Super Admin from scripts/create_super_admin.py (Super Admin 1.1).
        role="client",
        email=pending.email,
        first_name=pending.first_name,
        date_of_birth=pending.date_of_birth,
        country=pending.country,
        state=pending.state,
        zip_code=pending.zip_code or None,  # empty only on attempts from before 6 Nov
        password_hash=pending.password_hash,
        email_verified_at=now,
        # The trial starts now, for its length in the plan catalogue (Super Admin 8.1).
        trial_ends_at=now + timedelta(days=catalog.trial_days()),
        # The account's wrong-code locks count from here, not the attempt's own tries.
        password_changed_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # an account with this email appeared meanwhile
        db.rollback()
        raise AppError(409, "email_taken", EMAIL_TAKEN, "email") from None
    policies = list(
        db.scalars(select(PolicyVersion).where(PolicyVersion.id.in_(pending.policy_version_ids)))
    )
    accounts.record_acceptances(db, user, policies, request)
    audit.record(
        db,
        "auth.signed_up",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    audit.record(db, "auth.email_verified", actor_id=user.id, request=request)
    # Tells the owner, in case someone else verified a sign-up for their email.
    send(emails.account_created(user.email))
    # The used code moves to the account, so using it again gets 1.1's "request a new code".
    # This attempt and every other one for the email go; their codes are left closed with no
    # owner (ON DELETE SET NULL).
    challenge.used_at = now
    challenge.pending_sign_up = None
    challenge.user = user
    db.delete(pending)
    db.flush()
    # SKIP LOCKED: an attempt another verify holds is left for the purge, so two verifies at
    # once can't deadlock (the other one then gets "already exists").
    others = (
        select(PendingSignUp.id)
        .where(PendingSignUp.email == user.email)
        .with_for_update(skip_locked=True)
    )
    db.execute(delete(PendingSignUp).where(PendingSignUp.id.in_(others)))
    signed_in = _sign_in_after_code(db, user, data.platform, request)
    db.commit()
    return signed_in


def resend_code(
    db: Session, send: SendEmail, data: ResendCodeRequest, request: Request
) -> VerificationRequired:
    # Every code email from one IP counts, so resends can't flood inboxes either.
    _check_ip_limit(db, request, "auth.code.sent")
    now = _now()
    challenge = db.get(VerificationChallenge, data.challenge_id)
    if challenge is None:
        raise AppError(400, "challenge_closed", RESEND_LIMIT["sign_in"])
    closed = RESEND_LIMIT[challenge.purpose]
    if challenge.user_id is None:
        owner = _lock_pending(db, challenge)  # the attempt first, then its code
    else:
        db.refresh(challenge, with_for_update=True)
        owner = challenge.user
    if owner is None or challenge.used_at is not None:
        raise AppError(400, "challenge_closed", closed)
    if now - challenge.sent_at < timedelta(seconds=settings.code_resend_seconds):
        raise AppError(429, "resend_too_soon", "Please wait a minute before asking for a new code.")
    if challenge.send_count >= settings.code_max_sends:
        # Waiting won't help: only a new sign-in or sign-up starts a new challenge.
        raise AppError(429, "too_many_resends", closed)
    if _codes_sent_last_hour(db, owner.id) >= settings.max_codes_sent_per_hour:
        raise AppError(429, "too_many_codes", TOO_MANY_CODES)

    # The new code replaces the old one with a fresh count of tries: stories 1.1 and 1.2 tell
    # a client who got it wrong 5 times to ask for a new code. Guessing stays capped by
    # code_max_sends per challenge, the per-IP limit, and for an account the wrong-code locks.
    code = new_code()
    challenge.code_hash = hash_secret(code)
    challenge.sent_at = now
    challenge.expires_at = now + timedelta(minutes=settings.code_ttl_minutes)
    challenge.send_count += 1
    challenge.attempts = 0
    if isinstance(owner, PendingSignUp):
        # Kept for pending_sign_up_minutes after its last code; its purge job checks again.
        owner.expires_at = max(
            owner.expires_at, now + timedelta(minutes=settings.pending_sign_up_minutes)
        )
    audit.record(
        db,
        "auth.code.sent",
        actor_id=owner.id,
        request=request,
        details={"purpose": challenge.purpose, "resend": True},
    )
    db.commit()
    send(_code_email(owner, code, challenge.purpose))
    return _verification_required(challenge)


# Story 1.4: sign out


def sign_out(db: Session, access_token: str | None, data: SignOutRequest, request: Request) -> None:
    """Ends this device's session and forgets the device, so its next sign-in needs 2FA.
    Other devices stay signed in. Works after a timeout too, and is safe to repeat."""
    session = None
    if access_token:
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_secret(access_token))
        )
    device = None
    if data.device_token:
        device = db.scalar(
            select(TrustedDevice).where(TrustedDevice.token_hash == hash_secret(data.device_token))
        )
    if session is not None and device is not None and device.user_id != session.user_id:
        device = None  # another account's device: leave it alone
    user_id = session.user_id if session else device.user_id if device else None

    changed = False  # repeats are safe, but only a real sign-out is recorded
    device_ids: set[uuid.UUID] = set()
    if session is not None:
        if session.revoked_at is None:
            session.revoked_at = _now()
            changed = True
        if session.trusted_device_id is not None:
            device_ids.add(session.trusted_device_id)
    if device is not None:
        device_ids.add(device.id)
    if device_ids:
        # Other sessions on that device go too: they relied on it being trusted.
        db.execute(
            update(UserSession)
            .where(UserSession.trusted_device_id.in_(device_ids), UserSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        deleted = db.execute(delete(TrustedDevice).where(TrustedDevice.id.in_(device_ids)))
        changed = changed or deleted.rowcount > 0
    if changed:  # also after a timeout, when only the device token matched
        audit.record(db, "auth.signed_out", actor_id=user_id, request=request)
    db.commit()


# Story 1.3: forgot password


def request_password_reset(
    db: Session, send: SendEmail, data: ForgotPasswordRequest, request: Request
) -> None:
    """Emails a reset link if the account exists. The response is the same either way."""
    _check_ip_limit(db, request, "auth.password_reset.requested")
    now = _now()
    user = db.scalar(select(User).where(User.email == data.email).with_for_update())

    if user is None or user.status != "active":
        audit.record(
            db,
            "auth.password_reset.requested",
            request=request,
            details={"sent": False, "reason": "no_active_account"},
        )
        db.commit()
        return

    cooldown_start = now - timedelta(seconds=settings.reset_request_cooldown_seconds)
    recent = db.scalar(
        select(PasswordResetToken.id).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.created_at > cooldown_start
        )
    )
    if recent is not None:  # a link was just sent; don't flood the inbox
        audit.record(
            db,
            "auth.password_reset.requested",
            actor_id=user.id,
            request=request,
            details={"sent": False, "reason": "cooldown"},
        )
        db.commit()
        return

    # Only the newest link works.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_secret(token),
            expires_at=now + timedelta(minutes=settings.reset_link_ttl_minutes),
        )
    )
    audit.record(
        db,
        "auth.password_reset.requested",
        actor_id=user.id,
        request=request,
        details={"sent": True},
    )
    db.commit()
    send(_password_reset_email(user, token))


def _check_reset_row(row: PasswordResetToken | None) -> None:
    if row is None or row.used_at is not None:
        # Story 1.3 has one message for an expired, used or unknown link.
        raise AppError(400, "reset_link_invalid", RESET_LINK_EXPIRED)
    if row.expires_at <= _now():
        raise AppError(400, "reset_link_expired", RESET_LINK_EXPIRED)


def check_reset_token(db: Session, token: str) -> PasswordResetToken:
    row = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_secret(token))
    )
    _check_reset_row(row)
    return row


def reset_password(
    db: Session, send: SendEmail, data: ResetPasswordRequest, request: Request
) -> None:
    _check_ip_limit(db, request, "auth.password_reset.failed")
    now = _now()
    try:
        row = check_reset_token(db, data.token)
        # User first, then the link, as everywhere else; then check the link again under
        # the lock, in case a parallel request has just used it.
        db.refresh(row.user, with_for_update=True)
        db.refresh(row, with_for_update=True)
        _check_reset_row(row)
    except AppError as error:
        audit.record(
            db, "auth.password_reset.failed", request=request, details={"reason": error.code}
        )
        db.commit()
        raise
    user = row.user
    if verify_password(data.new_password, user.password_hash)[0]:
        # Counted by the IP limit above; and after a few, the link closes, so a link can't be
        # used to test guesses at the current password.
        audit.record(
            db,
            "auth.password_reset.failed",
            actor_id=user.id,
            request=request,
            details={"reason": "password_reused"},
        )
        reused = _count_events(
            db, "auth.password_reset.failed", now - row.created_at, actor_id=user.id
        )
        if reused >= settings.reset_link_max_failures:
            row.used_at = now
        db.commit()
        raise AppError(400, "password_reused", PASSWORD_REUSED, "new_password")

    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = now  # earlier wrong codes stop counting
    user.failed_sign_ins = 0  # a reset is the way out of a lock
    user.locked_until = None
    _close_open_secrets(db, user)  # this link, and any other open link or code
    _revoke_sessions(db, user)
    _forget_devices(db, user)  # the next sign-in needs 2FA (story 1.3)
    audit.record(db, "auth.password_reset.completed", actor_id=user.id, request=request)
    db.commit()
    send(_password_changed_email(user))


# Story 12.2: change password while signed in


def change_password(
    db: Session,
    send: SendEmail,
    session: UserSession,
    data: ChangePasswordRequest,
    request: Request,
) -> None:
    """Story 11.2. If the database fails at any point, nothing changes and the client is asked
    to try again."""
    try:
        _change_password(db, session, data, request)
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", CHANGE_PASSWORD_FAILED) from None
    send(_password_changed_email(session.user))


def _change_password(
    db: Session, session: UserSession, data: ChangePasswordRequest, request: Request
) -> None:
    user = session.user
    db.refresh(user, with_for_update=True)
    if not verify_password(data.current_password, user.password_hash)[0]:
        audit.record(db, "auth.password_change.failed", actor_id=user.id, request=request)
        window = timedelta(minutes=settings.lockout_minutes)
        failures = _count_events(db, "auth.password_change.failed", window, actor_id=user.id)
        if failures >= settings.max_failed_sign_ins:
            # Someone holding this session is guessing the password: end the session.
            session.revoked_at = _now()
            audit.record(
                db,
                "auth.session_revoked",
                actor_id=user.id,
                request=request,
                details={"reason": "wrong_current_password"},
            )
            db.commit()
            raise AppError(401, "signed_out", SIGNED_OUT)
        db.commit()
        raise AppError(
            400,
            "current_password_wrong",
            "Your current password isn’t right. Please try again.",
            "current_password",
        )
    if verify_password(data.new_password, user.password_hash)[0]:
        raise AppError(
            400,
            "password_reused",
            PASSWORD_REUSED,
            "new_password",
        )

    user.password_hash = hash_password(data.new_password)
    # Changing it proves the current password on a live session, so it ends a lock too (the
    # owner may be locked out elsewhere because someone is guessing codes with the old one).
    user.password_changed_at = _now()
    user.failed_sign_ins = 0
    user.locked_until = None
    _close_open_secrets(db, user)
    # This device stays signed in; every other device is signed out straight away.
    _revoke_sessions(db, user, keep=session)
    _forget_devices(db, user, keep_id=session.trusted_device_id)
    audit.record(db, "auth.password_changed", actor_id=user.id, request=request)
    db.commit()
