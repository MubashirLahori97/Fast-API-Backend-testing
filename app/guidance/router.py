from fastapi import APIRouter, Depends, Request, Response

from app.accounts.dependencies import ClientSession, consented_session
from app.conversations.dependencies import OwnedConversation
from app.core.database import DbSession
from app.guidance import documents, service
from app.guidance.dependencies import OwnedProviderNote
from app.guidance.schemas import (
    AppointmentIn,
    CreateProviderNotes,
    GuidanceSummaryOut,
    NotesCard,
    NotesResult,
    NotesText,
    Paper,
    ProviderNotesOut,
    SpecialtyOut,
    SummaryCard,
)
from app.oracle.dependencies import OracleService
from app.profiles.dependencies import OwnedProfile

# The policy gate applies to every route here, including ones added later.
router = APIRouter(tags=["guidance"], dependencies=[Depends(consented_session)])

PDF_RESPONSE = {200: {"content": {"application/pdf": {}}}}


def _pdf(pdf: bytes, name: str) -> Response:
    # Made on request and never stored; the app adds Cache-Control: no-store (app/main.py).
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": documents.content_disposition(name)},
    )


# Guidance summaries (story 3.3)


@router.post("/conversations/{conversation_id}/guidance-summary", status_code=201)
def share_summary(
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    response: Response,
    db: DbSession,
) -> GuidanceSummaryOut:
    """Story 3.3: writes the conversation's summary, or updates it with what the client shared
    since. Call it when a reply carries a "guidance_summary" widget. Answers 201 for the first
    summary, 200 for an update or when there's nothing new."""
    summary, created = service.share_summary(db, conversation, session.user, oracle, request)
    if not created:
        response.status_code = 200
    return summary


@router.get("/conversations/{conversation_id}/guidance-summary")
def get_summary(
    conversation: OwnedConversation, session: ClientSession, db: DbSession
) -> GuidanceSummaryOut:
    """Story 3.3: the conversation's summary, viewable during the free trial too."""
    return service.get_summary(db, conversation, session.user)


@router.get(
    "/conversations/{conversation_id}/guidance-summary/pdf",
    response_class=Response,
    responses=PDF_RESPONSE,
)
def download_summary(
    conversation: OwnedConversation,
    session: ClientSession,
    request: Request,
    db: DbSession,
    paper: Paper = "letter",
) -> Response:
    """Story 3.3's Download Summary (PDF). Locked during the free trial (403
    `upgrade_required`)."""
    pdf, name = service.summary_pdf(db, conversation, session.user, paper, request)
    return _pdf(pdf, name)


@router.get("/profiles/{profile_id}/guidance-summaries")
def list_summaries(profile: OwnedProfile, db: DbSession) -> list[SummaryCard]:
    """The profile's summaries, newest first, for My Visit Notes (story 5.1)."""
    return service.list_summaries(db, profile)


# Provider-ready notes (stories 3.4 and 3.5). /provider-notes/specialties comes before
# /provider-notes/{notes_id}, so it isn't read as an id.


@router.get("/provider-notes/specialties")
def list_specialties() -> list[SpecialtyOut]:
    """Story 3.4's specialty dropdown, from the settings, with Other last."""
    return service.list_specialties()


@router.post("/conversations/{conversation_id}/provider-notes", status_code=201)
def create_notes(
    body: CreateProviderNotes,
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    response: Response,
    db: DbSession,
) -> NotesResult:
    """Story 3.4's Create my notes. Answers 201 with the notes, or 200 when the Oracle asks a
    question first (`next`) or the request was sent before."""
    result, created = service.create_notes(db, conversation, body, session.user, oracle, request)
    if not created:
        response.status_code = 200
    return result


@router.get("/conversations/{conversation_id}/provider-notes")
def list_conversation_notes(
    conversation: OwnedConversation, session: ClientSession, db: DbSession
) -> list[NotesCard]:
    """The conversation's notes, upcoming appointments first."""
    return service.list_conversation_notes(db, conversation, session.user)


@router.get("/profiles/{profile_id}/provider-notes")
def list_profile_notes(
    profile: OwnedProfile, session: ClientSession, db: DbSession
) -> list[NotesCard]:
    """The profile's notes for My Visit Notes (story 5.1): upcoming appointments first,
    soonest first, then the rest, newest first."""
    return service.list_profile_notes(db, profile, session.user)


@router.get("/provider-notes/{notes_id}")
def get_notes(note: OwnedProviderNote, session: ClientSession, db: DbSession) -> ProviderNotesOut:
    """Story 3.5's notes screen: the latest version. Viewable during the free trial."""
    return service.get_notes(db, note, session.user)


@router.put("/provider-notes/{notes_id}/appointment")
def update_appointment(
    body: AppointmentIn,
    note: OwnedProviderNote,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    db: DbSession,
) -> NotesResult:
    """Edit appointment (stories 3.4 and 3.5): the specialty, provider name and date, and
    nothing else. A new specialty rewrites the notes; a new date reschedules the reminders."""
    return service.update_appointment(db, note, body, session.user, oracle, request)


@router.post("/provider-notes/{notes_id}/refresh")
def refresh_notes(
    note: OwnedProviderNote,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    db: DbSession,
) -> NotesResult:
    """Story 3.5: the Oracle updates the notes from the conversation, after the client asked
    for a change there. Call it when a reply carries an "update_provider_notes" widget."""
    return service.refresh_notes(db, note, session.user, oracle, request)


@router.get("/provider-notes/{notes_id}/text")
def copy_notes(
    note: OwnedProviderNote, session: ClientSession, request: Request, db: DbSession
) -> NotesText:
    """Story 3.5's Copy text: the full notes as plain text. Locked during the free trial (403
    `upgrade_required`)."""
    return service.notes_text(db, note, session.user, request)


@router.get("/provider-notes/{notes_id}/pdf", response_class=Response, responses=PDF_RESPONSE)
def download_notes(
    note: OwnedProviderNote,
    session: ClientSession,
    request: Request,
    db: DbSession,
    paper: Paper = "letter",
) -> Response:
    """Story 3.5's Download PDF and Print, laid out for Letter or A4 (`paper`). Locked during
    the free trial (403 `upgrade_required`)."""
    pdf, name = service.notes_pdf(db, note, session.user, paper, request)
    return _pdf(pdf, name)
