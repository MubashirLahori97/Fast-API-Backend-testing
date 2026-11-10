import uuid

from fastapi import APIRouter, Depends, Request, Response

from app.accounts.dependencies import ClientSession, consented_session
from app.core.database import DbSession
from app.health import service
from app.health.schemas import (
    AnswerIn,
    CircleMapOut,
    HealthFactConfirmed,
    HealthFactOut,
    HealthProfileEdit,
    HealthProfileOut,
    HealthProfileSaved,
)
from app.profiles.dependencies import UsableProfile

# The policy gate applies to every route here. UsableProfile is OwnedProfile (404 unless the
# profile is this account's) plus a finished intake, and not turned off or being deleted.
router = APIRouter(
    prefix="/profiles", tags=["health profile"], dependencies=[Depends(consented_session)]
)


@router.get("/{profile_id}/health-profile")
def get_health_profile(
    profile: UsableProfile, session: ClientSession, db: DbSession
) -> HealthProfileOut:
    """Story 6.1's My Health: the sections and questions that apply to this profile, with
    their answers and the completion percentage. 403 upgrade_required during the free trial."""
    return service.get_health_profile(db, profile, session.user)


@router.patch("/{profile_id}/health-profile")
def save_health_profile(
    edit: HealthProfileEdit,
    profile: UsableProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> HealthProfileSaved:
    """Saves answers (a section's Edit, or a step of Complete my profile), removes answers or
    whole sections, and changes About you's gender identity and pronouns. Answers the health
    profile as it is afterwards: questions that now apply appear, and ones that don't are
    hidden."""
    return service.save_health_profile(db, profile, edit, session.user, request)


@router.get("/{profile_id}/health-profile/circle-map")
def get_circle_map(profile: UsableProfile, session: ClientSession, db: DbSession) -> CircleMapOut:
    """Story 6.1's Hypothalamus Circle Map: the map's areas and symptoms, with the profile's
    symptoms (from My Health and its conversations) highlighted, and the line "This map shows
    how symptoms can connect to the hypothalamus. It isn’t a diagnosis." The map is a
    placeholder until Deborah's is in. 403 upgrade_required during the free trial."""
    return service.get_circle_map(db, profile, session.user)


@router.get(
    "/{profile_id}/health-profile/circle-map/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_circle_map(profile: UsableProfile, session: ClientSession, db: DbSession) -> Response:
    """The Circle Map as a one-page PDF, to download and print (6.1). Made on request and never
    stored; the app adds Cache-Control: no-store (app/main.py)."""
    pdf, name = service.circle_map_pdf(db, profile, session.user)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{profile_id}/health-facts")
def list_health_facts(
    profile: UsableProfile,
    session: ClientSession,
    db: DbSession,
    conversation_id: uuid.UUID | None = None,
) -> list[HealthFactOut]:
    """Changes a logged visit suggests (5.2: the Oracle asks before updating the health
    profile), still waiting for an answer. Details from conversations aren't here: since the
    6 Nov 19:22 stories they're saved straight away (3.1). `conversation_id` only finds facts
    saved before that change."""
    return service.list_facts(db, profile, session.user, conversation_id)


@router.patch("/{profile_id}/health-facts/{fact_id}")
def edit_health_fact(
    fact_id: uuid.UUID,
    body: AnswerIn,
    profile: UsableProfile,
    session: ClientSession,
    db: DbSession,
) -> HealthFactOut:
    """Changes a pending fact's value before it's saved."""
    return service.edit_fact(db, profile, session.user, fact_id, body)


@router.post("/{profile_id}/health-facts/{fact_id}/confirm")
def confirm_health_fact(
    fact_id: uuid.UUID,
    profile: UsableProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
    body: AnswerIn | None = None,
) -> HealthFactConfirmed:
    """Saves the fact to the health profile, as coming from its conversation. Send a body to
    save an edited value instead."""
    return service.confirm_fact(db, profile, session.user, fact_id, body, request)


@router.post("/{profile_id}/health-facts/{fact_id}/discard")
def discard_health_fact(
    fact_id: uuid.UUID, profile: UsableProfile, session: ClientSession, db: DbSession
) -> HealthFactOut:
    """The client doesn't want it saved."""
    return service.discard_fact(db, profile, session.user, fact_id)
