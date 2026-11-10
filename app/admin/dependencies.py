"""Who may use the admin panel's endpoints.

The admin panel uses the same sessions as the apps (`CurrentSession`), plus a role check:
`users.role` is `client`, `admin` or `super_admin`. A client's token gets the same 404 as an
unknown admin route would, so the admin API isn't advertised to clients.

Admins' sessions follow their own rules (app/auth/dependencies.py): signed out after 15 idle
minutes, and signed out straight away when deactivated.
"""

from typing import Annotated

from fastapi import Depends

from app.auth.dependencies import BackgroundSession, CurrentSession
from app.auth.models import UserSession
from app.auth.service import ADMIN_ROLES
from app.core.errors import AppError

__all__ = [
    "ADMIN_ROLES",
    "AdminBackgroundSession",
    "AdminSession",
    "SuperAdminSession",
]


def _not_found() -> AppError:
    return AppError(404, "not_found", "We couldn’t find that page.")


def _check_admin(session: UserSession) -> UserSession:
    if session.user.role not in ADMIN_ROLES:
        raise _not_found()
    return session


def admin_session(session: CurrentSession) -> UserSession:
    """A signed-in Admin or the Super Admin (Super Admin and Admin stories)."""
    return _check_admin(session)


def admin_background_session(session: BackgroundSession) -> UserSession:
    """AdminSession for requests the admin panel makes by itself (polling the bell's count):
    they don't count as activity, so an unused tab is still signed out after 15 minutes."""
    return _check_admin(session)


def super_admin_session(session: CurrentSession) -> UserSession:
    """The Super Admin only: managing Admins, subscriptions and pricing, Consent Management and
    the Audit Logs (Super Admin 7.2's "everything except...", 6 Nov 19:22). Approving knowledge
    base content is checked in its service."""
    if session.user.role != "super_admin":
        if session.user.role in ADMIN_ROLES:
            raise AppError(403, "super_admin_only", "Only the Super Admin can do this.")
        raise _not_found()
    return session


AdminSession = Annotated[UserSession, Depends(admin_session)]
AdminBackgroundSession = Annotated[UserSession, Depends(admin_background_session)]
SuperAdminSession = Annotated[UserSession, Depends(super_admin_session)]
