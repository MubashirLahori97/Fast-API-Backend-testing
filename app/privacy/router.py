from fastapi import APIRouter, Request, Response

from app.accounts.dependencies import PrivacySession
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse
from app.privacy import service
from app.privacy.schemas import DeletionRequested, PrivacyOut

router = APIRouter(tags=["privacy"])


# Story 11.4: Privacy & Data. These take PrivacySession, not the policy gate: they keep working
# while consent is revoked or policies are pending, during a deletion's grace period, and for an
# invited teen who has lost access. Once an account is locked for deletion (after its grace
# period) they're refused too (see app/privacy/service.py).


@router.get("/me/privacy")
def privacy(session: PrivacySession, db: DbSession) -> PrivacyOut:
    """The Privacy & Data screen: the accepted policies with their versions and dates, what the
    client can do (export, revoke consent, delete), any open deletion request with the grace
    period's banner, and the names and texts the Delete Account flow shows."""
    return service.privacy_screen(db, session.user)


@router.get(
    "/me/export",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}, "description": "The data file."}},
)
def export_my_data(session: PrivacySession, request: Request, db: DbSession) -> Response:
    """Export My Data: a JSON file of the account's own data, downloaded straight away and not
    kept on the server. A parent's export never includes their invited teens'."""
    body, filename = service.export_my_data(db, session.user, request)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/me/consent/revoke")
def revoke_consent(session: PrivacySession, request: Request, db: DbSession) -> MessageResponse:
    """Revoke Consent, after the app has shown what will happen and the client confirmed. Signs
    out every device, this one included. Not available to teens with their own account."""
    return MessageResponse(message=service.revoke_consent(db, session.user, request))


@router.post("/me/deletion-request", status_code=201)
def request_deletion(
    session: PrivacySession, request: Request, db: DbSession, send: EmailLater
) -> DeletionRequested:
    """Delete Account (Delete My Information for a teen with their own account), once the client
    has confirmed. Starts the 10-day grace period with full use; the client is acknowledged
    straight away, and the answer's message is the grace period's banner."""
    return service.request_deletion(db, session.user, send, request)
