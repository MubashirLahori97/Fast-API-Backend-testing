import uuid

from fastapi import APIRouter, Depends, Request

from app.accounts.dependencies import ClientSession, consented_session
from app.core.database import DbSession
from app.profiles.dependencies import OwnedProfile
from app.wellness import service
from app.wellness.schemas import (
    ItemTicked,
    LibraryOut,
    PlanCardScreen,
    TickItem,
    WellnessPlanScreen,
)

# The policy gate applies to every route here. Everything is reached through OwnedProfile:
# another account's profile, a teen's own included, gets the same 404 as an unknown one.
router = APIRouter(
    prefix="/profiles", tags=["wellness plan"], dependencies=[Depends(consented_session)]
)


@router.get("/{profile_id}/wellness-plan")
def get_plan(profile: OwnedProfile, session: ClientSession, db: DbSession) -> WellnessPlanScreen:
    """Story 7.1's plan screen: the latest version, or the "No plan yet" message. 403
    `upgrade_required` during the free trial."""
    return service.get_plan(db, profile, session.user)


@router.get("/{profile_id}/wellness-plan/card")
def get_card(profile: OwnedProfile, session: ClientSession, db: DbSession) -> PlanCardScreen:
    """The Wellness Plan card (Home Dashboard, My Health): the current focus and the To Do
    progress dots. `card` is null when there's no plan yet."""
    return service.get_card(db, profile, session.user)


@router.put("/{profile_id}/wellness-plan/items/{item_id}")
def tick_item(
    item_id: uuid.UUID,
    body: TickItem,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> ItemTicked:
    """Ticks a To Do item, or unticks one ticked by mistake."""
    return service.tick_item(db, profile, session.user, item_id, body.done, request)


@router.get("/{profile_id}/wellness-protocols")
def get_library(profile: OwnedProfile, db: DbSession) -> LibraryOut:
    """The Wellness Protocols library for this profile, with the content published in the
    knowledge base: no product tabs, shop links or cleanses for teens and children. Each
    section's `key` is its link target."""
    return service.library(db, profile)
