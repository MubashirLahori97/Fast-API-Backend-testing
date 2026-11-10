from typing import Literal

from fastapi import APIRouter, Depends, Request, Response

from app.accounts.dependencies import ClientSession, consented_session
from app.core.database import DbSession
from app.guidance.dependencies import OwnedProviderNote
from app.profiles.dependencies import OwnedProfile
from app.visits import listing, service
from app.visits.dependencies import OwnedVisitLog
from app.visits.schemas import (
    CreateVisitLog,
    VisitLogForm,
    VisitLogIn,
    VisitLogOut,
    VisitLogSaved,
    VisitNotesOut,
    VisitNotesSearch,
)

# The policy gate applies to every route here. Profiles are reached through OwnedProfile and
# logs through OwnedVisitLog: another account's id gets the same 404 as an unknown one.
router = APIRouter(tags=["visit notes"], dependencies=[Depends(consented_session)])


# My Visit Notes (story 5.1)


@router.get("/profiles/{profile_id}/visit-notes")
def list_visit_notes(profile: OwnedProfile, session: ClientSession, db: DbSession) -> VisitNotesOut:
    """Story 5.1: the profile's guidance summaries, provider-ready notes and logged visits,
    upcoming appointments first (soonest first), then newest first. 403 `upgrade_required`
    during the free trial."""
    return listing.visit_notes(db, profile, session.user)


@router.post("/profiles/{profile_id}/visit-notes/search")
def search_visit_notes(
    body: VisitNotesSearch, profile: OwnedProfile, session: ClientSession, db: DbSession
) -> VisitNotesOut:
    """Story 5.1's search, by title, topic, specialty or provider name, in the same order. A
    POST so the search text never goes in a URL."""
    return listing.visit_notes(db, profile, session.user, body.query)


# Logging visits (story 5.2)


@router.get("/profiles/{profile_id}/visit-logs/form")
def standalone_form(profile: OwnedProfile, session: ClientSession) -> VisitLogForm:
    """+ Log a visit: the form with only the first name and date of birth filled in."""
    return service.standalone_form(profile, session.user)


@router.get("/provider-notes/{notes_id}/visit-log/form")
def notes_form(note: OwnedProviderNote, session: ClientSession, db: DbSession) -> VisitLogForm:
    """Log visit on a set of notes (or the post-visit notification): the form pre-filled from
    the notes, with the notes to show read-only. 409 `visit_already_logged` once logged."""
    return service.notes_form(db, note, session.user)


@router.post("/profiles/{profile_id}/visit-logs", status_code=201)
def create_visit_log(
    body: CreateVisitLog,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    response: Response,
    db: DbSession,
) -> VisitLogSaved:
    """Save (5.2). Answers 201, or 200 when the same `client_request_id` was saved before."""
    saved, created = service.create_visit_log(db, profile, body, session.user, request)
    if not created:
        response.status_code = 200
    return saved


@router.get("/visit-logs/{visit_log_id}")
def get_visit_log(log: OwnedVisitLog, session: ClientSession, db: DbSession) -> VisitLogOut:
    """A logged visit, with the Oracle's review once it's ready."""
    return service.get_visit_log(db, log, session.user)


@router.put("/visit-logs/{visit_log_id}")
def update_visit_log(
    body: VisitLogIn,
    log: OwnedVisitLog,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> VisitLogSaved:
    """Edit (5.2): the whole form again. The review and the Wellness Plan update run again."""
    return service.update_visit_log(db, log, body, session.user, request)


@router.delete("/visit-logs/{visit_log_id}", status_code=204)
def delete_visit_log(
    log: OwnedVisitLog,
    session: ClientSession,
    request: Request,
    db: DbSession,
    plan_items: Literal["keep", "remove"] | None = None,
) -> Response:
    """Delete visit log (5.2), after "Delete this visit log? This can’t be undone.". When the
    visit added Wellness Plan items, `plan_items` says whether to keep or remove them; without
    it the answer is 409 `plan_items_choice_required` with 5.2's question."""
    service.delete_visit_log(db, log, session.user, plan_items, request)
    return Response(status_code=204)
