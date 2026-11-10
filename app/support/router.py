from fastapi import APIRouter, Depends, Request, Response

from app.accounts.dependencies import ClientSession, consented_session
from app.core.database import DbSession
from app.profiles.dependencies import OwnedProfile
from app.support import service
from app.support.schemas import SupportRequestBody, SupportRequestSent

# The policy gate applies to every route here, including ones added later.
router = APIRouter(tags=["support"], dependencies=[Depends(consented_session)])


@router.post("/profiles/{profile_id}/support-requests", status_code=201)
def send_request_about_profile(
    body: SupportRequestBody,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    response: Response,
    db: DbSession,
) -> SupportRequestSent:
    """Story 10.1: Contact support team (kind "talk_to_support") or Consult with support team
    (kind "consultation"), about the active profile. The team's list shows that profile ("Sent
    by Sarah about Azka"). Answers 200 with the saved request when it's a resend."""
    result, created = service.send_request(db, session.user, profile, body, request)
    if not created:
        response.status_code = 200
    return result


@router.post("/support-requests", status_code=201)
def send_request(
    body: SupportRequestBody,
    session: ClientSession,
    request: Request,
    response: Response,
    db: DbSession,
) -> SupportRequestSent:
    """Story 10.1's forms, for a client with no active profile yet (before their first
    intake is finished). Otherwise use the profile's route, so the team knows who it's about.
    Answers 200 with the saved request when it's a resend."""
    result, created = service.send_request(db, session.user, None, body, request)
    if not created:
        response.status_code = 200
    return result
