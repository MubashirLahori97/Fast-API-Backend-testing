import uuid

from fastapi import APIRouter, Query, Request

from app.admin.admins import service
from app.admin.admins.schemas import (
    AdminDetails,
    AdminPage,
    AdminResult,
    AdminStatus,
    DeactivateAdminIn,
    EditAdminIn,
    InviteAdminIn,
)
from app.admin.dependencies import SuperAdminSession
from app.core.config import settings
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse

# Super Admin 7.1: "Only the Super Admin can open Admin Management. Admins can't see it."
router = APIRouter(prefix="/admin/admins", tags=["admin: admin management"])


@router.get("")
def list_admins(
    session: SuperAdminSession,
    db: DbSession,
    search: str | None = Query(default=None, max_length=200),
    status: AdminStatus | None = None,
    limit: int = Query(
        default=settings.admin_list_page_size, ge=1, le=settings.admin_list_max_page_size
    ),
    offset: int = Query(default=0, ge=0),
) -> AdminPage:
    """Story 7.1's listing, newest first: name, email, status (Invite pending, Invite expired,
    Active or Deactivated), date added and last active date."""
    return service.list_admins(db, search, status, limit, offset)


@router.post("", status_code=201)
def invite_admin(
    data: InviteAdminIn,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> AdminResult:
    """Story 7.2's Send invite: emails a Set up your account link, valid 24 hours."""
    message, admin = service.invite_admin(db, send, session.user, data, request)
    return AdminResult(message=message, admin=admin)


@router.get("/{admin_id}")
def get_admin(admin_id: uuid.UUID, session: SuperAdminSession, db: DbSession) -> AdminDetails:
    """Story 7.1's Admin Details, with who added them, the Admin permissions and the actions
    available now."""
    return service.get_admin(db, admin_id)


@router.patch("/{admin_id}")
def edit_admin(
    admin_id: uuid.UUID,
    data: EditAdminIn,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> AdminResult:
    """Edit: the first and last name. The email address can't be changed."""
    message, admin = service.edit_admin(db, session.user, admin_id, data, request)
    return AdminResult(message=message, admin=admin)


@router.post("/{admin_id}/deactivate")
def deactivate_admin(
    admin_id: uuid.UUID,
    data: DeactivateAdminIn,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> AdminResult:
    """Deactivate, with a reason: the Admin is signed out straight away and can't sign in."""
    message, admin = service.deactivate_admin(db, session.user, admin_id, data, request)
    return AdminResult(message=message, admin=admin)


@router.post("/{admin_id}/reactivate")
def reactivate_admin(
    admin_id: uuid.UUID, session: SuperAdminSession, request: Request, db: DbSession
) -> AdminResult:
    message, admin = service.reactivate_admin(db, session.user, admin_id, request)
    return AdminResult(message=message, admin=admin)


@router.post("/{admin_id}/resend-invite")
def resend_invite(
    admin_id: uuid.UUID,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> AdminResult:
    """Resend invite (also for an expired one): a new link, and the old one stops working."""
    message, admin = service.resend_invite(db, send, session.user, admin_id, request)
    return AdminResult(message=message, admin=admin)


@router.post("/{admin_id}/cancel-invite")
def cancel_invite(
    admin_id: uuid.UUID, session: SuperAdminSession, request: Request, db: DbSession
) -> MessageResponse:
    """Cancel invite: the link stops working, and the Admin is removed from the listing."""
    return MessageResponse(message=service.cancel_invite(db, session.user, admin_id, request))
