from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.models import UserSession
from app.auth.security import hash_secret
from app.auth.service import ADMIN_ROLES, SIGNED_OUT, deactivated_message
from app.core import audit
from app.core.config import settings
from app.core.database import DbSession
from app.core.errors import AppError

# auto_error=False lets us answer with our own error format. It also adds an
# "Authorize" button to the Swagger UI.
bearer = HTTPBearer(auto_error=False)
BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]

NOT_SIGNED_IN = "Please sign in to continue."
SESSION_EXPIRED = "Your session has expired. Please sign in again."
SIGNED_OUT_INACTIVE = "You’ve been signed out after a period of inactivity. Please sign in again."


def admin_signed_out_inactive() -> str:
    """Super Admin 1.1 and Admin 1.2, with the configured number of minutes (15)."""
    return (
        f"You’ve been signed out after {settings.admin_session_idle_minutes} minutes of "
        "inactivity. Please sign in again."
    )


def _ended(reason: str | None, role: str) -> AppError:
    """The error for a session that has ended. A timeout or a deactivated account keeps its
    own message on every later request too, such as the parallel ones an app sends when it
    wakes up; anything else gets the general one. Admins get their stories' wording."""
    if reason == "session_expired":
        return AppError(401, "session_expired", SESSION_EXPIRED)
    if reason == "signed_out_inactive":
        message = admin_signed_out_inactive() if role in ADMIN_ROLES else SIGNED_OUT_INACTIVE
        return AppError(401, "signed_out_inactive", message)
    if reason == "account_deactivated":
        return AppError(403, "account_deactivated", deactivated_message(role))
    return AppError(401, "signed_out", SIGNED_OUT)


def _idle_minutes(session: UserSession) -> int | None:
    """How long a session may sit unused: 15 minutes for admins on every platform (Super
    Admin 1.1, Admin 1.2), 30 for clients on the web, and no server limit for the mobile app
    (story 1.2)."""
    if session.user.role in ADMIN_ROLES:
        return settings.admin_session_idle_minutes
    if session.platform == "web":
        return settings.web_session_idle_minutes
    return None


def current_session(request: Request, db: DbSession, credentials: BearerToken) -> UserSession:
    """The signed-in session for this request, or a 401. Applies the session's maximum age,
    and the inactivity timeout: 30 minutes on the web (story 1.2), 15 for admins (Super Admin
    1.1). Counts as activity."""
    return _checked_session(request, db, credentials, counts_as_activity=True)


def background_session(request: Request, db: DbSession, credentials: BearerToken) -> UserSession:
    """The same checks as current_session, for requests the app makes by itself (polling the
    notification bell, say). They don't count as activity, so an open but unused web tab is
    still signed out after 30 idle minutes (story 1.2)."""
    return _checked_session(request, db, credentials, counts_as_activity=False)


def _checked_session(
    request: Request, db: DbSession, credentials: BearerToken, *, counts_as_activity: bool
) -> UserSession:
    if credentials is None:
        raise AppError(401, "not_signed_in", NOT_SIGNED_IN)
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_secret(credentials.credentials))
    )
    if session is None:
        raise AppError(401, "not_signed_in", NOT_SIGNED_IN)
    if session.revoked_at is not None:
        reason = session.revoked_reason
        if reason == "account_deactivated" and session.user.status == "active":
            reason = None  # reactivated since: the client just needs to sign in again
        raise _ended(reason, session.user.role)

    now = datetime.now(UTC)
    idle_minutes = _idle_minutes(session)
    reason = None
    if session.expires_at <= now:
        reason = "session_expired"
    elif idle_minutes is not None and session.last_seen_at + timedelta(minutes=idle_minutes) <= now:
        reason = "signed_out_inactive"
    if reason is not None:
        # The device stays trusted (story 1.2: 2FA isn't needed at every sign-in); an
        # explicit sign-out is what forgets it.
        session.revoked_at = now
        session.revoked_reason = reason
        audit.record(
            db,
            "auth.session_timed_out",
            actor_id=session.user_id,
            request=request,
            details={"reason": reason},
        )
        db.commit()
        raise _ended(reason, session.user.role)

    if session.user.status != "active":
        session.revoked_at = now
        session.revoked_reason = "account_deactivated"
        audit.record(
            db,
            "auth.session_revoked",
            actor_id=session.user_id,
            request=request,
            details={"reason": "deactivated"},
        )
        db.commit()
        raise _ended(session.revoked_reason, session.user.role)

    # Record activity at most once a minute, to keep writes down.
    if counts_as_activity and now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        db.commit()
    return session


CurrentSession = Annotated[UserSession, Depends(current_session)]
BackgroundSession = Annotated[UserSession, Depends(background_session)]
