from fastapi import APIRouter, Request, Response

from app.auth import service
from app.auth.dependencies import BearerToken
from app.auth.schemas import (
    ForgotPasswordRequest,
    ResendCodeRequest,
    ResetPasswordRequest,
    ResetTokenRequest,
    SignedIn,
    SignInRequest,
    SignOutRequest,
    SignUpCheck,
    SignUpRequest,
    VerificationRequired,
    VerifyRequest,
)
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup/check", status_code=204)
def check_sign_up_details(data: SignUpCheck) -> Response:
    """Story 1.1, after step 2: checks the date of birth and state, and stops anyone
    under the age of majority before they give an email or password. Saves nothing."""
    service.check_age(data)
    return Response(status_code=204)


@router.post("/signup", status_code=201)
def sign_up(
    data: SignUpRequest, request: Request, db: DbSession, send: EmailLater
) -> VerificationRequired:
    """Story 1.1. Emails a code to verify the address. The account is created when the code
    is verified (POST /auth/verify)."""
    return service.sign_up(db, send, data, request)


@router.post("/signin")
def sign_in(
    data: SignInRequest, request: Request, db: DbSession, send: EmailLater
) -> SignedIn | VerificationRequired:
    """Story 1.2. Signs in directly on a trusted device; otherwise emails a code."""
    return service.sign_in(db, send, data, request)


@router.post("/verify")
def verify(data: VerifyRequest, request: Request, db: DbSession, send: EmailLater) -> SignedIn:
    """Checks the emailed code (after sign-up or sign-in) and signs the client in. A
    sign-up's code creates the account."""
    return service.verify(db, send, data, request)


@router.post("/verify/resend")
def resend_code(
    data: ResendCodeRequest, request: Request, db: DbSession, send: EmailLater
) -> VerificationRequired:
    return service.resend_code(db, send, data, request)


@router.post("/signout", status_code=204)
def sign_out(
    request: Request,
    db: DbSession,
    credentials: BearerToken,
    data: SignOutRequest | None = None,
) -> Response:
    """Story 1.4. Signs out this device only. Send the device_token too, so the device is
    forgotten even if the session already timed out. Always answers 204."""
    token = credentials.credentials if credentials else None
    service.sign_out(db, token, data or SignOutRequest(), request)
    return Response(status_code=204)


@router.post("/password/forgot", status_code=202)
def forgot_password(
    data: ForgotPasswordRequest, request: Request, db: DbSession, send: EmailLater
) -> MessageResponse:
    """Story 1.3. Same answer whether or not the email is registered."""
    service.request_password_reset(db, send, data, request)
    return MessageResponse(
        message="If an account exists for this email, we’ve sent a link to reset your password."
    )


@router.post("/password/reset/check")
def check_reset_link(data: ResetTokenRequest, db: DbSession) -> MessageResponse:
    """Lets the app show an expired or used link before the client types a new password."""
    service.check_reset_token(db, data.token)
    return MessageResponse(message="This reset link is valid.")


@router.post("/password/reset")
def reset_password(
    data: ResetPasswordRequest, request: Request, db: DbSession, send: EmailLater
) -> MessageResponse:
    service.reset_password(db, send, data, request)
    return MessageResponse(message="Your password has been reset. Please sign in.")
