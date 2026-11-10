from fastapi import APIRouter, Request

from app.admin.dependencies import AdminSession
from app.admin.profile import service
from app.admin.profile.schemas import AdminProfileEdit, AdminProfileOut, AdminProfileUpdated
from app.auth import service as auth_service
from app.auth.schemas import ChangePasswordRequest
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse

# Admins and the Super Admin alike (Super Admin 12.1 and 12.2, Admin 8.1 and 8.2). Sign Out is
# the shared POST /auth/signout, which ends this device's session and is audited.
router = APIRouter(prefix="/admin/me", tags=["admin: my profile"])


@router.get("")
def get_my_profile(session: AdminSession, db: DbSession) -> AdminProfileOut:
    """Super Admin 12.1's My Profile: name, email, role, sign-in times and two-step
    verification (always On)."""
    return service.my_profile(db, session)


@router.patch("")
def update_my_profile(
    edit: AdminProfileEdit, session: AdminSession, request: Request, db: DbSession
) -> AdminProfileUpdated:
    """Edit and Save: the first and last name. The email address can't be changed here."""
    profile = service.update_my_profile(db, session, edit, request)
    return AdminProfileUpdated(message=service.PROFILE_UPDATED, profile=profile)


@router.post("/password")
def change_password(
    data: ChangePasswordRequest,
    session: AdminSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> MessageResponse:
    """Super Admin 12.2 and Admin 8.2's Reset Password: keeps this session, signs out every
    other one, and emails a confirmation. Same rules and messages as the clients' (story 11.2),
    which are Admin 8.2's exact wording."""
    auth_service.change_password(db, send, session, data, request)
    return MessageResponse(message="Your password has been changed.")
