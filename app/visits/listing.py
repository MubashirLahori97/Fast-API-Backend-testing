"""My Visit Notes (story 5.1): one list per profile of its guidance summaries, provider-ready
notes and logged visits.

- **Order:** notes with an upcoming appointment (today or later, on Hawaii's date, and not yet
  logged) first, soonest first, with an "Upcoming · Cardiology · 14 Nov" label; then everything
  else, newest first. It's worked out on every request, so a note moves down the day after its
  appointment and moves when the date is edited, with nothing to re-sort.
- **One card per visit:** a visit logged for a set of notes shows on the notes' card (Ask the
  Oracle and Edit instead of Log visit); a standalone visit has its own card. A deleted
  conversation's summary and notes aren't listed; a visit logged for them becomes standalone.
- **Search (under 1 second):** three queries by profile, each on an index on `profile_id`,
  that read only the cards' fields (the previews come straight out of the JSONB, not whole
  documents), then matching in memory: every word of the search must appear in the card's
  title, topic, specialty or provider name, ignoring case. A profile has at most a few hundred
  notes, so a search takes a few milliseconds. Matching in Python also searches the titles and
  specialty labels the backend writes (they aren't columns), and keeps working once Phase 4
  encrypts these fields, which SQL can't search. The search text comes in a POST body, never
  the URL.

Greyed out during the free trial; the notes can still be opened in their conversations (3.5).
"""

import unicodedata
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.conversations.models import Conversation
from app.core.ages import us_today
from app.core.errors import AppError
from app.guidance import documents, specialties
from app.guidance.models import GuidanceSummary, ProviderNote, ProviderNoteVersion
from app.profiles.models import Profile
from app.visits import service
from app.visits.models import VisitLog
from app.visits.schemas import VisitNoteCard, VisitNotesOut

# Story 5.1's messages.
NO_NOTES = (
    "You don’t have any visit notes yet. Start a conversation and I’ll help you get ready for "
    "your next appointment."
)
NO_RESULTS = "No notes match your search."
LOAD_FAILED = "We couldn’t load your notes. Please try again."
# Not in the stories: a summary's card when its conversation has no topic yet.
SUMMARY_TITLE = "Guidance summary"


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _notes_title(profile: Profile, account: User, label: str) -> str:
    """The notes' own title (3.5's "Notes for my Cardiology appointment")."""
    if profile.is_self:
        return f"Notes for my {label} appointment"
    return f"Notes for {service.first_name(profile, account)}’s {label} appointment"


def _upcoming_label(label: str, day: date) -> str:
    """5.1's "Upcoming · Cardiology · 14 Nov"."""
    return f"Upcoming · {label} · {day.day} {documents.MONTHS[day.month - 1]}"


def _summary_cards(db: Session, profile: Profile) -> list[VisitNoteCard]:
    rows = db.execute(
        select(
            GuidanceSummary.id,
            GuidanceSummary.conversation_id,
            GuidanceSummary.shared_at,
            Conversation.topic,
            GuidanceSummary.content["what_im_hearing"].astext,
        )
        .join(Conversation, GuidanceSummary.conversation_id == Conversation.id)
        .where(
            GuidanceSummary.profile_id == profile.id,
            GuidanceSummary.content.is_not(None),
            Conversation.profile_id == profile.id,
            Conversation.deleted_at.is_(None),
        )
    ).all()
    return [
        VisitNoteCard(
            type="guidance_summary",
            id=summary_id,
            conversation_id=conversation_id,
            title=topic[:1].upper() + topic[1:] if topic else SUMMARY_TITLE,
            preview=documents.preview(hearing or ""),
            created_at=shared_at,
            topic=topic,
            specialty_label=None,
            provider_name=None,
            appointment_date=None,
            visit_date=None,
            upcoming=False,
            upcoming_label=None,
            visit_log_id=None,
            can_log_visit=False,
            can_download=True,
            ask_prompt=None,
        )
        for summary_id, conversation_id, shared_at, topic, hearing in rows
    ]


def _cards(db: Session, profile: Profile, account: User) -> list[VisitNoteCard]:
    cards = _summary_cards(db, profile)
    notes = db.execute(
        select(
            ProviderNote, Conversation.topic, ProviderNoteVersion.content["chief_complaint"].astext
        )
        .join(Conversation, ProviderNote.conversation_id == Conversation.id)
        .join(
            ProviderNoteVersion,
            (ProviderNoteVersion.note_id == ProviderNote.id)
            & (ProviderNoteVersion.version == ProviderNote.version),
        )
        .where(
            ProviderNote.profile_id == profile.id,
            Conversation.profile_id == profile.id,
            Conversation.deleted_at.is_(None),
        )
    ).all()
    logs = db.scalars(select(VisitLog).where(VisitLog.profile_id == profile.id)).all()
    note_ids = {note.id for note, _, _ in notes}
    logged: dict[uuid.UUID, VisitLog] = {
        log.provider_note_id: log for log in logs if log.provider_note_id in note_ids
    }
    today = us_today()
    for note, topic, complaint in notes:
        label = specialties.label(note.specialty, note.specialty_other)
        log = logged.get(note.id)
        upcoming = (
            log is None and note.appointment_date is not None and note.appointment_date >= today
        )
        cards.append(
            VisitNoteCard(
                type="provider_notes",
                id=note.id,
                conversation_id=note.conversation_id,
                title=_notes_title(profile, account, label),
                preview=documents.preview(complaint or ""),
                created_at=note.created_at,
                topic=topic,
                specialty_label=label,
                provider_name=note.provider_name,
                appointment_date=note.appointment_date,
                visit_date=log.visit_date if log else None,
                upcoming=upcoming,
                upcoming_label=_upcoming_label(label, note.appointment_date) if upcoming else None,
                visit_log_id=log.id if log else None,
                can_log_visit=log is None,
                can_download=True,
                ask_prompt=service.ask_prompt(profile, account, log) if log else None,
            )
        )
    for log in logs:
        if log.provider_note_id in note_ids:
            continue  # shown on its notes' card
        label = specialties.label(log.specialty, log.specialty_other)
        cards.append(
            VisitNoteCard(
                type="visit_log",
                id=log.id,
                conversation_id=None,
                title=service.title(profile, account, label),
                preview=documents.preview(log.reason),
                created_at=log.created_at,
                topic=log.reason,
                specialty_label=label,
                provider_name=log.provider_name,
                appointment_date=None,
                visit_date=log.visit_date,
                upcoming=False,
                upcoming_label=None,
                visit_log_id=log.id,
                can_log_visit=False,
                can_download=False,  # 5.1: logged visits stay in the app
                ask_prompt=service.ask_prompt(profile, account, log),
            )
        )
    upcoming = sorted((c for c in cards if c.upcoming), key=lambda c: c.appointment_date)
    others = sorted((c for c in cards if not c.upcoming), key=_newest_first)
    return [*upcoming, *others]


def _newest_first(card: VisitNoteCard) -> tuple[float, str]:
    return (-card.created_at.timestamp(), str(card.id))


def _matches(card: VisitNoteCard, words: list[str]) -> bool:
    haystack = _normalized(
        " ".join(
            part
            for part in (card.title, card.topic, card.specialty_label, card.provider_name)
            if part
        )
    )
    return all(word in haystack for word in words)


def visit_notes(
    db: Session, profile: Profile, account: User, query: str | None = None
) -> VisitNotesOut:
    """The active profile's My Visit Notes, optionally searched (5.1)."""
    service.check_unlocked(account, service.NOTES_LOCKED)
    try:
        cards = _cards(db, profile, account)
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "load_failed", LOAD_FAILED) from None
    if not cards:
        return VisitNotesOut(cards=[], message=NO_NOTES)
    words = _normalized(query or "").split()
    if not words:
        return VisitNotesOut(cards=cards, message=None)
    found = [card for card in cards if _matches(card, words)]
    return VisitNotesOut(cards=found, message=None if found else NO_RESULTS)
