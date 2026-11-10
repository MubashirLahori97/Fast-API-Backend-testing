"""Admin 1.1: accepting an invitation. No sign-in needed: the invite token, from the link's
fragment, is sent in each request's body."""

from fastapi import APIRouter, Request

from app.admin.auth import service
from app.admin.auth.schemas import (
    AcceptInvitationRequest,
    InvitationOut,
    InvitationTokenRequest,
    SetupCodeRequest,
    SetupCodeSent,
)
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse

router = APIRouter(prefix="/admin/invitations", tags=["admin: account setup"])


@router.post("/check")
def check_invitation(
    data: InvitationTokenRequest, request: Request, db: DbSession
) -> InvitationOut:
    """Opens the setup screen: the first and last name and email from the invite, which can't
    be changed. 400 `invite_expired` for an expired, used, cancelled or unknown link."""
    return service.check_invitation(db, data.token, request)


@router.post("/accept")
def accept_invitation(
    data: AcceptInvitationRequest, request: Request, db: DbSession, send: EmailLater
) -> SetupCodeSent:
    """Set up account: checks the password rules and emails a 6-digit code to the invite's
    address. The account is created once the code is verified."""
    return service.accept_invitation(db, send, data, request)


@router.post("/verify")
def verify_setup_code(data: SetupCodeRequest, request: Request, db: DbSession) -> MessageResponse:
    """The right code creates the Admin's account: "Your account is ready. Please sign in."
    The Admin then signs in with their email, password and a new code."""
    return MessageResponse(message=service.verify_setup_code(db, data, request))


@router.post("/verify/resend")
def resend_setup_code(
    data: InvitationTokenRequest, request: Request, db: DbSession, send: EmailLater
) -> SetupCodeSent:
    return service.resend_setup_code(db, send, data.token, request)
