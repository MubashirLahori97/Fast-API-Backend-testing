"""Guidance summaries (story 3.3) and provider-ready notes (stories 3.4 and 3.5).

The Oracle decides in the conversation when a summary or notes are due, with a widget on its
reply (app/oracle/contract.py); the app then calls these. Both are written from the
conversation, with the same gates as a reply (3.1, 3.2): a usable profile, a trial or plan, the
Health Consent, every message safety-checked, and no emergency or crisis hold. The Oracle is
asked with no transaction or lock held; one request at a time per summary or set of notes holds
a short claim, as replies do.

Summaries and notes are health data: stored, never logged (Oracle failures by class name only),
and their audit events hold ids only. The decisions are in
docs/decisions/phase-5-guidance-and-notes.md.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, get_args

from fastapi import Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.conversations import safety
from app.conversations import service as conversations
from app.conversations.models import Conversation, Message
from app.conversations.schemas import MessageOut
from app.conversations.widgets import prepare_widget
from app.core import audit
from app.core.ages import is_adult, us_today
from app.core.config import settings
from app.core.errors import ACTION_FAILED, AppError, database_errors_retryable
from app.core.schemas import clean_line, clean_message
from app.guidance import documents, reminders, specialties
from app.guidance.models import GuidanceSummary, ProviderNote, ProviderNoteVersion
from app.guidance.schemas import (
    AddedDetailOut,
    AddedToHealthProfileOut,
    AppointmentIn,
    AppointmentOut,
    CreateProviderNotes,
    GuidanceSummaryOut,
    NotesCard,
    NotesHeaderOut,
    NotesResult,
    NotesText,
    Paper,
    ProviderNotesOut,
    SpecialtyOut,
    SummaryCard,
)
from app.guidance.specialties import Appointment
from app.health import service as health
from app.oracle import contract
from app.oracle.contract import PRODUCT_LINK, PROVIDER_NOTES, Oracle, OracleError, Turn
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.wellness import protocols
from app.wellness import triggers as wellness_triggers

logger = logging.getLogger(__name__)

# Story 3.3's messages.
SUMMARY_LOCKED = "Subscribe to download and keep your guidance."
SUMMARY_DOWNLOAD_FAILED = "We couldn’t download your summary. Please try again."
# Story 3.4's and 3.5's messages.
NOTES_READY_FOR = "Your notes for {provider} are ready. Take them with you to your appointment."
NOTES_READY = "Your notes are ready. Take them with you when you see your provider."
NOT_YET_BOOKED = (
    "From what you’ve shared, {provider} would be a good place to start. I’ve put together notes "
    "you can take with you when you book."
)
NOTES_UPDATED = "I’ve updated your notes for your {specialty} appointment."
NOTES_FAILED = "I couldn’t create your notes just now. Please try again."
NOTES_LOCKED = "Subscribe to download, print and copy your provider notes."
NOTES_DOWNLOAD_FAILED = "We couldn’t download your notes. Please try again."
NOTES_COPIED = "Your notes have been copied."
# Not in the stories (docs/decisions/phase-5-guidance-and-notes.md).
SUMMARY_NOT_FOUND = "There’s no summary for this conversation yet."
SUMMARY_IN_PROGRESS = "I’m still working on your summary. Please wait a moment."
NOTES_NOT_FOUND = "We couldn’t find those notes."
NOTES_IN_PROGRESS = "I’m still working on your notes. Please wait a moment."
TOO_MANY_NOTES = (
    "You’ve already made a lot of notes in this conversation. Please edit the appointment on "
    "one of them instead."
)

# Caps on what's kept from the Oracle, so one bad answer can't fill a page or a column.
TEXT_MAX_LENGTH = 4000
LINE_MAX_LENGTH = 500
PROTOCOL_MAX_LENGTH = 100
ITEMS_MAX = 20
RECOMMENDATION_KINDS = frozenset(get_args(contract.RecommendationKind))
NOTES_STATUSES = frozenset(get_args(contract.NotesStatus))


def _safety_hold_error() -> AppError:
    """Story 3.2: nothing new is written while an emergency or crisis waits for an option."""
    return AppError(409, "safety_hold", safety.OPTION_NOT_SELECTED)


def _not_found() -> AppError:
    return AppError(404, "conversation_not_found", conversations.CONVERSATION_NOT_FOUND)


def _first_name(profile: Profile, account: User) -> str:
    return clean_line((account.first_name if profile.is_self else profile.first_name) or "")


def _downloads_unlocked(account: User) -> bool:
    """Downloading, printing and copying are locked during the free trial (3.3, 3.5): the
    plan's "downloads" feature, which also covers a teen with their own account (Phase 3b)."""
    return not entitlements.feature_access(account)["downloads"]


def _check_downloads_unlocked(account: User, message: str) -> None:
    """Refuses a locked download with the story's own upgrade message, rather than 9.1's
    general one (entitlements.check_feature)."""
    if not _downloads_unlocked(account):
        raise AppError(403, "upgrade_required", message)


# What the Oracle is given


def _messages(db: Session, conversation: Conversation) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    )


def _history(messages: list[Message]) -> list[Turn]:
    return [
        Turn(
            role=message.role,
            text=message.text,
            widgets=message.widgets or [],
            answer=message.answer,
        )
        for message in messages[-settings.oracle_output_history_messages :]
    ]


def _latest_client_message(messages: list[Message]) -> Message:
    # Every conversation starts with a client message.
    return next(message for message in reversed(messages) if message.role == "client")


def _prepare_oracle_call(
    db: Session, conversation: Conversation, account: User, oracle: Oracle
) -> list[Message]:
    """The gates before the Oracle writes a summary or notes, the same as for a reply (3.1,
    3.2). Every client message must have passed its safety check: the checks still to come run
    here first, with no lock held. Returns the conversation's messages."""
    profile = conversation.profile
    with database_errors_retryable(db):
        check_can_use(profile)
        entitlements.check_can_talk(account)
        if not conversations.has_health_consent(db, profile):
            raise AppError(403, "health_consent_required", conversations.HEALTH_CONSENT_REQUIRED)
        unchecked = list(
            db.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.role == "client",
                    Message.safety_level.is_(None),
                )
            )
        )
        db.commit()
    for message in unchecked:
        if conversations.check_message_safety(db, message, profile, oracle) is None:
            raise AppError(503, "safety_check_failed", ACTION_FAILED)
    with database_errors_retryable(db):
        if safety.open_hold(db, conversation.id) is not None:
            raise _safety_hold_error()
        messages = _messages(db, conversation)
        db.commit()
    return messages


def _check_still_open(db: Session, conversation: Conversation) -> None:
    """Before saving what the Oracle wrote: the conversation may have been deleted, or a
    message sent meanwhile may have opened a hold. Locks the conversation, as saving a reply
    does, until the caller commits."""
    db.refresh(conversation, with_for_update=True)
    if conversation.deleted_at is not None:
        raise _not_found()
    if safety.open_hold(db, conversation.id) is not None:
        raise _safety_hold_error()


def _claim(db: Session, model: type[GuidanceSummary | ProviderNote], record_id: uuid.UUID):
    """Claims the record for one Oracle request, or returns None while another has it. A claim
    older than settings.guidance_claim_seconds belongs to a request that died."""
    now = datetime.now(UTC)
    return db.scalar(
        update(model)
        .where(
            model.id == record_id,
            or_(
                model.generation_started_at.is_(None),
                model.generation_started_at
                < now - timedelta(seconds=settings.guidance_claim_seconds),
            ),
        )
        .values(generation_started_at=now)
        .returning(model.generation_started_at)
    )


def _release(
    db: Session,
    model: type[GuidanceSummary | ProviderNote],
    record_id: uuid.UUID,
    claimed_at: datetime,
) -> None:
    """Lets the client try again straight away. Only this request's own claim is released."""
    try:
        db.rollback()
        db.execute(
            update(model)
            .where(model.id == record_id, model.generation_started_at == claimed_at)
            .values(generation_started_at=None)
        )
        db.commit()
    except Exception:  # the claim expires on its own
        db.rollback()


def _add_oracle_line(
    db: Session, conversation: Conversation, text: str, note: ProviderNote | None = None
) -> Message:
    """An Oracle line in the conversation, with the notes card when it's about notes (3.4:
    "The notes open in the conversation, with an Edit appointment button")."""
    line = Message(
        conversation_id=conversation.id,
        role="oracle",
        text=text,
        widgets=[{"kind": PROVIDER_NOTES, "notes_id": str(note.id)}] if note else None,
    )
    db.add(line)
    conversation.last_message_at = datetime.now(UTC)
    db.flush()
    return line


def _save_line(db: Session, conversation: Conversation, text: str) -> MessageOut:
    """Saves the Oracle's question (more information first, or which provider "Other" is)."""
    with database_errors_retryable(db):
        _check_still_open(db, conversation)
        line = _add_oracle_line(db, conversation, text)
        db.commit()
    return MessageOut.model_validate(line)


# Cleaning what the Oracle returned. Anything of the wrong shape is dropped; a required section
# that's missing makes the whole answer a failure (OracleError).


def _text(value: object, *, required: bool = False) -> str | None:
    cleaned = clean_message(value)[:TEXT_MAX_LENGTH] if isinstance(value, str) else ""
    if required and not cleaned:
        raise OracleError("A required section was empty.")
    return cleaned or None


def _line(value: object) -> str | None:
    return clean_line(value)[:LINE_MAX_LENGTH] or None if isinstance(value, str) else None


def _lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [line for value in values[:ITEMS_MAX] if (line := _line(value))]


def _items(values: object, kind: type) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [value for value in values[:ITEMS_MAX] if isinstance(value, kind)]


def _recommendation(item: contract.Recommendation) -> dict[str, Any] | None:
    """A product or link, kept only with a label and an https URL (the 3.1 product link rules).
    No prices are kept: the contract has none."""
    link = prepare_widget({"kind": PRODUCT_LINK, "label": item.label, "url": item.url}, adult=True)
    if link is None:
        return None
    kind = item.kind if item.kind in RECOMMENDATION_KINDS else "other"
    return {
        "label": link["label"],
        "url": link["url"],
        "kind": kind,
        "why": _line(item.why),
        # Genesis products: the label's directions, word for word (3.3).
        "label_directions": _line(item.label_directions) if kind == "genesis_product" else None,
    }


def _test_url(test: contract.TestToDiscuss, name: str, *, adult: bool) -> str | None:
    """The link Deborah supplied for a test (3.3), an information link: adults only, like other
    links, and only an https URL (the 3.1 link rules)."""
    if not adult or not isinstance(test.url, str):
        return None
    link = prepare_widget({"kind": PRODUCT_LINK, "label": name, "url": test.url}, adult=True)
    return link["url"] if link else None


def _clean_summary(result: object, *, adult: bool) -> dict[str, Any]:
    """The summary as it's stored, in the shape of contract.GuidanceSummary. Recommendations
    are kept for adults only (3.3)."""
    if not isinstance(result, contract.GuidanceSummary):
        raise OracleError("The summary isn't a GuidanceSummary.")
    if result.stage not in ("first_look", "full"):
        raise OracleError("The summary has an unknown stage.")
    tests = [
        {"name": name, "why": _text(test.why), "url": _test_url(test, name, adult=adult)}
        for test in _items(result.tests_worth_discussing, contract.TestToDiscuss)
        if (name := _line(test.name))
    ]
    steps = [
        {"text": text, "protocol": _protocol(step.protocol)}
        for step in _items(result.what_you_can_do_now, contract.ActionStep)
        if (text := _line(step.text))
    ]
    recommendations = []
    if adult:
        recommendations = [
            kept
            for item in _items(result.recommendations, contract.Recommendation)
            if (kept := _recommendation(item))
        ]
    return {
        "stage": result.stage,
        "what_im_hearing": _text(result.what_im_hearing, required=True),
        "what_this_may_mean": _text(result.what_this_may_mean, required=True),
        "word_from_the_oracle": _text(result.word_from_the_oracle, required=True),
        "hypothalamic_connection": _text(result.hypothalamic_connection),
        "questions_for_provider": _lines(result.questions_for_provider),
        "tests_worth_discussing": tests,
        "what_you_can_do_now": steps,
        "recommendations": recommendations,
        "recommended_next_steps": _lines(result.recommended_next_steps),
        "provider_visit_relevant": result.provider_visit_relevant is True,
        "still_needed": _lines(result.still_needed) if result.stage == "first_look" else [],
    }


def _protocol(value: object) -> str | None:
    return clean_line(value)[:PROTOCOL_MAX_LENGTH] or None if isinstance(value, str) else None


def _summary_from_content(content: dict[str, Any]) -> contract.GuidanceSummary:
    """The stored summary as the contract's dataclass, for the Oracle to update."""
    return contract.GuidanceSummary(
        stage=content["stage"],
        what_im_hearing=content["what_im_hearing"],
        what_this_may_mean=content["what_this_may_mean"],
        word_from_the_oracle=content["word_from_the_oracle"],
        hypothalamic_connection=content.get("hypothalamic_connection"),
        questions_for_provider=list(content.get("questions_for_provider") or []),
        tests_worth_discussing=[
            contract.TestToDiscuss(
                name=test["name"], why=test.get("why") or "", url=test.get("url")
            )
            for test in content.get("tests_worth_discussing") or []
        ],
        what_you_can_do_now=[
            contract.ActionStep(text=step["text"], protocol=step.get("protocol"))
            for step in content.get("what_you_can_do_now") or []
        ],
        recommendations=[
            contract.Recommendation(
                label=item["label"],
                url=item["url"],
                kind=item["kind"],
                why=item.get("why"),
                label_directions=item.get("label_directions"),
            )
            for item in content.get("recommendations") or []
        ],
        recommended_next_steps=list(content.get("recommended_next_steps") or []),
        provider_visit_relevant=bool(content.get("provider_visit_relevant")),
        still_needed=list(content.get("still_needed") or []),
    )


def _clean_notes(result: contract.ProviderNotes, *, adult: bool) -> dict[str, Any]:
    """Ready notes as they're stored, in the shape of contract.ProviderNotes. The Genesis Gold®
    note and products are for adults only (3.4)."""
    labs = [
        {"test": test, "value": value}
        for lab in _items(result.reported_lab_values, contract.ReportedLabValue)
        if (test := _line(lab.test)) and (value := _line(lab.value))
    ]
    requested = [
        {"name": name, "reason": _line(lab.reason), "primary": lab.primary is not False}
        for lab in _items(result.labs_requested, contract.RequestedLab)
        if (name := _line(lab.name))
    ]
    return {
        "chief_complaint": _text(result.chief_complaint, required=True),
        "clinical_context": _text(result.clinical_context, required=True),
        "reported_lab_values": labs,
        "labs_requested": requested,
        "questions": _lines(result.questions),
        "medications": _lines(result.medications),
        "taking_genesis_gold": adult and result.taking_genesis_gold is True,
        "red_flags": _lines(result.red_flags),
        "recommendation": _text(result.recommendation, required=True),
        "referral": _text(result.referral),
        "mentions_products": adult and result.mentions_products is True,
    }


# Guidance summaries (story 3.3)


def _summary_row(db: Session, conversation: Conversation) -> GuidanceSummary | None:
    return db.scalar(
        select(GuidanceSummary).where(GuidanceSummary.conversation_id == conversation.id)
    )


def share_summary(
    db: Session, conversation: Conversation, account: User, oracle: Oracle, request: Request
) -> tuple[GuidanceSummaryOut, bool]:
    """Writes the conversation's summary, or updates the one it has (3.3: one per conversation,
    updated rather than repeated). Returns (summary, created).

    With no client message since the summary was written, it's returned as it is and the
    Oracle isn't asked, so asking again costs nothing. A full summary schedules the two-week
    follow-up check-in."""
    profile = conversation.profile
    messages = _prepare_oracle_call(db, conversation, account, oracle)
    latest = _latest_client_message(messages)
    with database_errors_retryable(db):
        summary = _summary_row(db, conversation)
        if summary is not None and summary.content is not None:
            if summary.covers_message_id == latest.id:
                db.commit()
                return summary_out(db, summary, account), False
        if summary is None:
            db.execute(
                insert(GuidanceSummary)
                .values(id=uuid.uuid4(), conversation_id=conversation.id, profile_id=profile.id)
                .on_conflict_do_nothing(index_elements=["conversation_id"])
            )
            summary = _summary_row(db, conversation)
        claimed_at = _claim(db, GuidanceSummary, summary.id)
        db.commit()
    if claimed_at is None:
        raise AppError(409, "summary_in_progress", SUMMARY_IN_PROGRESS)

    try:
        previous = _summary_from_content(summary.content) if summary.content else None
        context = conversations.profile_context(profile, account, db)
        db.commit()  # no transaction is held while the Oracle runs
        result = oracle.summarize(context, _history(messages), previous)
        content = _clean_summary(result, adult=is_adult(profile.date_of_birth))
    except Exception as error:  # the AI service failed, or answered something unusable
        logger.warning(
            "Guidance summary failed: %s (conversation %s)", type(error).__name__, conversation.id
        )
        _release(db, GuidanceSummary, summary.id, claimed_at)
        raise AppError(503, "summary_failed", ACTION_FAILED) from None

    try:
        with database_errors_retryable(db):
            _check_still_open(db, conversation)
            db.refresh(summary, with_for_update=True)
            created = summary.content is None
            now = datetime.now(UTC)
            summary.stage = content["stage"]
            summary.content = content
            summary.covers_message_id = latest.id
            summary.shared_at = summary.shared_at or now
            summary.content_updated_at = now
            summary.generation_started_at = None
            if content["stage"] == "full":
                reminders.schedule_guidance_follow_up(db, account, profile, conversation)
                # Phase 7 (7.1): the Wellness Plan is created or updated from it.
                wellness_triggers.summary_shared(db, account, profile, summary.id)
            audit.record(
                db,
                "guidance_summary.shared" if created else "guidance_summary.updated",
                actor_id=account.id,
                target_type="guidance_summary",
                target_id=summary.id,
                request=request,
                details={"conversation_id": str(conversation.id)},
            )
            db.commit()
    except AppError:
        _release(db, GuidanceSummary, summary.id, claimed_at)
        raise
    return summary_out(db, summary, account), created


def _shown_products(db: Session, summary: GuidanceSummary, profile: Profile) -> bool:
    """Products for adults only, and never during an emergency or crisis hold (3.3)."""
    return is_adult(profile.date_of_birth) and safety.open_hold(db, summary.conversation_id) is None


def summary_out(db: Session, summary: GuidanceSummary, account: User) -> GuidanceSummaryOut:
    profile = db.get(Profile, summary.profile_id)
    content = summary.content
    show_products = _shown_products(db, summary, profile)
    unlocked = _downloads_unlocked(account)
    adult = is_adult(profile.date_of_birth)
    library = protocols.load(db)
    protocols_shown = frozenset(
        key for key in protocols.SECTIONS if library.allowed(key, adult=adult)
    )
    return GuidanceSummaryOut(
        id=summary.id,
        conversation_id=summary.conversation_id,
        profile_id=summary.profile_id,
        stage=summary.stage,
        introduction=(
            documents.SUMMARY_INTRODUCTION
            if summary.stage == "full"
            else documents.FIRST_LOOK_INTRODUCTION
        ),
        sections=documents.summary_sections(
            content, show_products=show_products, protocols_shown=protocols_shown
        ),
        disclosure=(
            documents.SUMMARY_DISCLOSURE
            if documents.summary_products(content, show_products=show_products)
            else None
        ),
        disclaimer=documents.SUMMARY_DISCLAIMER,
        added_to_health_profile=_added_to_health_profile(db, summary, profile, account),
        offer_provider_notes=bool(content.get("provider_visit_relevant")),
        can_download=unlocked,
        locked_message=None if unlocked else SUMMARY_LOCKED,
        shared_at=summary.shared_at,
        updated_at=summary.content_updated_at,
    )


def _added_to_health_profile(
    db: Session, summary: GuidanceSummary, profile: Profile, account: User
) -> AddedToHealthProfileOut | None:
    """3.3's list below the summary: what the Oracle saved to the health profile from this
    conversation (`health.added_from_conversation`), whatever the summary's stage. None when
    nothing was added. Shown during the free trial too; there, Review in My Health shows the
    upgrade prompt (My Health is greyed out)."""
    added = health.added_from_conversation(db, profile, account, summary.conversation_id)
    if not added:
        return None
    locked = entitlements.feature_access(account)["my_health"]
    return AddedToHealthProfileOut(
        message=documents.ADDED_TO_HEALTH_PROFILE,
        details=[
            AddedDetailOut(
                question_key=detail.key,
                question=detail.question,
                answer=detail.answer,
                added_at=detail.added_at,
            )
            for detail in added
        ],
        can_review=not locked,
        review_locked_message=health.MY_HEALTH_LOCKED if locked else None,
    )


def _shared_summary(db: Session, conversation: Conversation) -> GuidanceSummary:
    summary = _summary_row(db, conversation)
    if summary is None or summary.content is None:
        raise AppError(404, "guidance_summary_not_found", SUMMARY_NOT_FOUND)
    return summary


def get_summary(db: Session, conversation: Conversation, account: User) -> GuidanceSummaryOut:
    return summary_out(db, _shared_summary(db, conversation), account)


def list_summaries(db: Session, profile: Profile) -> list[SummaryCard]:
    """The profile's summaries, newest first, for My Visit Notes (5.1). Deleted conversations'
    summaries aren't listed."""
    rows = db.execute(
        select(GuidanceSummary, Conversation.topic)
        .join(Conversation, GuidanceSummary.conversation_id == Conversation.id)
        .where(
            GuidanceSummary.profile_id == profile.id,
            GuidanceSummary.content.is_not(None),
            Conversation.profile_id == profile.id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(GuidanceSummary.content_updated_at.desc())
    ).all()
    return [
        SummaryCard(
            id=summary.id,
            conversation_id=summary.conversation_id,
            topic=topic,
            stage=summary.stage,
            preview=documents.preview(summary.content["what_im_hearing"]),
            shared_at=summary.shared_at,
            updated_at=summary.content_updated_at,
        )
        for summary, topic in rows
    ]


def summary_pdf(
    db: Session, conversation: Conversation, account: User, paper: Paper, request: Request
) -> tuple[bytes, str]:
    """Download Summary (PDF), locked during the trial (3.3). Returns (pdf, file name)."""
    _check_downloads_unlocked(account, SUMMARY_LOCKED)
    summary = _shared_summary(db, conversation)
    out = summary_out(db, summary, account)
    profile = db.get(Profile, summary.profile_id)
    first_name = _first_name(profile, account)
    updated = summary.content_updated_at.date()
    document = documents.Document(
        title=(
            "Your guidance summary" if profile.is_self else f"Guidance summary for {first_name}"
        ),
        subtitle=f"Updated {documents.show_date(updated)}",
        intro=out.introduction,
        sections=out.sections,
        disclosure=out.disclosure,
        disclaimer=out.disclaimer,
    )
    try:
        pdf = documents.to_pdf(document, paper)
    except Exception as error:
        logger.warning("Summary PDF failed: %s (summary %s)", type(error).__name__, summary.id)
        raise AppError(503, "download_failed", SUMMARY_DOWNLOAD_FAILED) from None
    with database_errors_retryable(db):
        audit.record(
            db,
            "guidance_summary.downloaded",
            actor_id=account.id,
            target_type="guidance_summary",
            target_id=summary.id,
            request=request,
        )
        db.commit()
    name = documents.file_name("Guidance-Summary", first_name, documents.file_date(updated))
    return pdf, name


# Provider-ready notes (stories 3.4 and 3.5)


def list_specialties() -> list[SpecialtyOut]:
    """3.4's dropdown, with Other last."""
    return [
        *(
            SpecialtyOut(code=option.code, label=option.label)
            for option in settings.provider_specialties
        ),
        SpecialtyOut(code=specialties.OTHER, label=specialties.OTHER_LABEL),
    ]


def _appointment(body: AppointmentIn, booking: str) -> Appointment:
    return specialties.read_appointment(
        specialty=body.specialty,
        specialty_other=body.specialty_other,
        provider_name=body.provider_name,
        appointment_date=body.appointment_date,
        booking=booking,
    )


def _ask_for_notes(
    db: Session,
    oracle: Oracle,
    profile: Profile,
    account: User,
    messages: list[Message],
    specialty: str,
    specialty_other: str | None,
    booked: bool,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Asks the Oracle for notes. Returns (status, content, line): the cleaned content when
    they're ready, or the line to add to the conversation when it needs to ask first."""
    request = contract.NotesSpecialty(
        code=specialty, name=specialties.label(specialty, specialty_other), booked=booked
    )
    try:
        context = conversations.profile_context(profile, account, db)
        db.commit()  # no transaction is held while the Oracle runs
        result = oracle.provider_notes(context, _history(messages), request)
        if not isinstance(result, contract.ProviderNotes) or result.status not in NOTES_STATUSES:
            raise OracleError("The notes aren't ProviderNotes.")
        if result.status == "more_information":
            return "more_questions", None, _text(result.question, required=True)
        if result.status == "unclear_specialty":
            if specialty != specialties.OTHER:
                raise OracleError("Only an Other specialty can be unclear.")
            text = specialties.UNCLEAR_SPECIALTY.format(text=specialty_other)
            return "clarify_specialty", None, text
        return "ready", _clean_notes(result, adult=is_adult(profile.date_of_birth)), None
    except Exception as error:  # the AI service failed, or answered something unusable
        logger.warning("Provider notes failed: %s (profile %s)", type(error).__name__, profile.id)
        raise AppError(503, "notes_failed", NOTES_FAILED) from None


def _current_version(db: Session, note: ProviderNote) -> ProviderNoteVersion:
    return db.scalar(
        select(ProviderNoteVersion).where(
            ProviderNoteVersion.note_id == note.id, ProviderNoteVersion.version == note.version
        )
    )


def _upcoming(day: date | None) -> bool:
    return day is not None and day >= us_today()


def _title(profile: Profile, account: User, label: str) -> str:
    """3.5's "Notes for my Cardiology appointment"."""
    if profile.is_self:
        return f"Notes for my {label} appointment"
    return f"Notes for {_first_name(profile, account)}’s {label} appointment"


def notes_out(db: Session, note: ProviderNote, account: User) -> ProviderNotesOut:
    profile = db.get(Profile, note.profile_id)
    version = _current_version(db, note)
    label = specialties.label(note.specialty, note.specialty_other)
    unlocked = _downloads_unlocked(account)
    return ProviderNotesOut(
        id=note.id,
        conversation_id=note.conversation_id,
        profile_id=note.profile_id,
        title=_title(profile, account, label),
        created_at=note.created_at,
        updated_at=version.created_at,
        version=note.version,
        appointment=AppointmentOut(
            specialty=note.specialty,
            specialty_other=note.specialty_other,
            specialty_label=label,
            provider_name=note.provider_name,
            appointment_date=note.appointment_date,
            upcoming=_upcoming(note.appointment_date),
        ),
        header=NotesHeaderOut(
            first_name=_first_name(profile, account),
            date_of_birth=profile.date_of_birth,
            specialty=label,
            provider_name=note.provider_name,
            appointment_date=note.appointment_date,
            medical_advocate=None if profile.is_self else clean_line(account.first_name),
        ),
        what_this_is=documents.WHAT_THIS_IS,
        sections=documents.notes_sections(version.content),
        disclosure=documents.notes_disclosure(version.content),
        disclaimer=documents.NOTES_DISCLAIMER,
        can_download=unlocked,
        locked_message=None if unlocked else NOTES_LOCKED,
    )


def _ready_line(appointment: Appointment) -> str:
    """3.4's "Notes ready", or "Not yet booked" for the Oracle's suggestion."""
    if not appointment.booked and appointment.specialty != specialties.PRIMARY_CARE:
        provider = specialties.provider(appointment.specialty, appointment.specialty_other)
        return NOT_YET_BOOKED.format(provider=provider)
    if appointment.provider_name:
        return NOTES_READY_FOR.format(provider=appointment.provider_name)
    return NOTES_READY


def create_notes(
    db: Session,
    conversation: Conversation,
    body: CreateProviderNotes,
    account: User,
    oracle: Oracle,
    request: Request,
) -> tuple[NotesResult, bool]:
    """Create my notes (3.4), from the conversation, for the appointment card. Returns (result,
    created). Safe to repeat with the same client_request_id.

    The Oracle may ask a few more questions first, or ask what an "Other" provider is: its
    question is added to the conversation, and no notes are made. Once made, the notes open in
    the conversation (an Oracle line with the notes card) and the reminders are scheduled."""
    profile = conversation.profile
    appointment = _appointment(body, body.booking)
    with database_errors_retryable(db):
        existing = db.scalar(
            select(ProviderNote).where(
                ProviderNote.conversation_id == conversation.id,
                ProviderNote.client_request_id == body.client_request_id,
            )
        )
        if existing is not None:
            return NotesResult(
                next="unchanged", notes=notes_out(db, existing, account), message=None
            ), False
        made = db.scalar(
            select(func.count())
            .select_from(ProviderNote)
            .where(ProviderNote.conversation_id == conversation.id)
        )
        db.commit()
    if made >= settings.max_provider_notes_per_conversation:
        raise AppError(409, "too_many_notes", TOO_MANY_NOTES)

    messages = _prepare_oracle_call(db, conversation, account, oracle)
    status, content, line_text = _ask_for_notes(
        db,
        oracle,
        profile,
        account,
        messages,
        appointment.specialty,
        appointment.specialty_other,
        appointment.booked,
    )
    if content is None:
        return NotesResult(
            next=status, notes=None, message=_save_line(db, conversation, line_text)
        ), False

    with database_errors_retryable(db):
        _check_still_open(db, conversation)
        note = ProviderNote(
            conversation_id=conversation.id,
            profile_id=profile.id,
            client_request_id=body.client_request_id,
            specialty=appointment.specialty,
            specialty_other=appointment.specialty_other,
            provider_name=appointment.provider_name,
            appointment_date=appointment.appointment_date,
            version=1,
        )
        db.add(note)
        db.flush()
        db.add(
            ProviderNoteVersion(
                note_id=note.id,
                version=1,
                reason="created",
                specialty=note.specialty,
                specialty_other=note.specialty_other,
                content=content,
                covers_message_id=_latest_client_message(messages).id,
            )
        )
        line = _add_oracle_line(db, conversation, _ready_line(appointment), note)
        reminders.schedule_appointment(db, account, profile, note)
        audit.record(
            db,
            "provider_notes.created",
            actor_id=account.id,
            target_type="provider_note",
            target_id=note.id,
            request=request,
            details={"conversation_id": str(conversation.id)},
        )
        try:
            db.commit()
        except IntegrityError:  # sent twice at once; the other request made them
            db.rollback()
            existing = db.scalar(
                select(ProviderNote).where(
                    ProviderNote.conversation_id == conversation.id,
                    ProviderNote.client_request_id == body.client_request_id,
                )
            )
            if existing is None:
                raise
            return NotesResult(
                next="unchanged", notes=notes_out(db, existing, account), message=None
            ), False
    return NotesResult(
        next="ready", notes=notes_out(db, note, account), message=MessageOut.model_validate(line)
    ), True


def _rewrite(
    db: Session,
    note: ProviderNote,
    account: User,
    oracle: Oracle,
    request: Request,
    *,
    appointment: Appointment | None,
) -> NotesResult:
    """A new version of the notes from the conversation: for a new specialty (`appointment`,
    which is saved with it), or the same one when the client asked the Oracle for a change.
    Nothing changes unless the Oracle's new notes are saved, so the content always matches the
    specialty."""
    conversation = db.get(Conversation, note.conversation_id)
    profile = conversation.profile
    messages = _prepare_oracle_call(db, conversation, account, oracle)
    latest = _latest_client_message(messages)
    with database_errors_retryable(db):
        if appointment is None and _current_version(db, note).covers_message_id == latest.id:
            db.commit()
            return NotesResult(next="unchanged", notes=notes_out(db, note, account), message=None)
        claimed_at = _claim(db, ProviderNote, note.id)
        db.commit()
    if claimed_at is None:
        raise AppError(409, "notes_in_progress", NOTES_IN_PROGRESS)

    specialty = appointment.specialty if appointment else note.specialty
    specialty_other = appointment.specialty_other if appointment else note.specialty_other
    try:
        status, content, line_text = _ask_for_notes(
            db, oracle, profile, account, messages, specialty, specialty_other, booked=True
        )
    except AppError:
        _release(db, ProviderNote, note.id, claimed_at)
        raise
    if content is None:
        _release(db, ProviderNote, note.id, claimed_at)
        message = _save_line(db, conversation, line_text)
        return NotesResult(next=status, notes=notes_out(db, note, account), message=message)

    try:
        with database_errors_retryable(db):
            _check_still_open(db, conversation)
            db.refresh(note, with_for_update=True)
            date_changed = False
            if appointment is not None:
                date_changed = appointment.appointment_date != note.appointment_date
                note.specialty = appointment.specialty
                note.specialty_other = appointment.specialty_other
                note.provider_name = appointment.provider_name
                note.appointment_date = appointment.appointment_date
            note.version += 1
            note.generation_started_at = None
            db.add(
                ProviderNoteVersion(
                    note_id=note.id,
                    version=note.version,
                    reason="specialty_changed" if appointment else "updated_from_conversation",
                    specialty=note.specialty,
                    specialty_other=note.specialty_other,
                    content=content,
                    covers_message_id=latest.id,
                )
            )
            label = specialties.label(note.specialty, note.specialty_other)
            line = _add_oracle_line(db, conversation, NOTES_UPDATED.format(specialty=label), note)
            if date_changed:
                reminders.schedule_appointment(db, account, profile, note)
            audit.record(
                db,
                "provider_notes.specialty_changed" if appointment else "provider_notes.updated",
                actor_id=account.id,
                target_type="provider_note",
                target_id=note.id,
                request=request,
                details={"version": note.version},
            )
            db.commit()
    except AppError:
        _release(db, ProviderNote, note.id, claimed_at)
        raise
    return NotesResult(
        next="ready", notes=notes_out(db, note, account), message=MessageOut.model_validate(line)
    )


def update_appointment(
    db: Session,
    note: ProviderNote,
    body: AppointmentIn,
    account: User,
    oracle: Oracle,
    request: Request,
) -> NotesResult:
    """Edit appointment (3.4, 3.5): the specialty, the provider's name and the date; only these
    can change, and the content stays read-only. Allowed during the free trial.

    - A new specialty: the Oracle rewrites the questions, tests and referral advice, saved as
      a new version, and says so in the conversation.
    - A new name or date: the header follows (it's built from these), and a new or removed date
      reschedules the reminders (a removed one schedules the booking follow-up instead)."""
    profile = db.get(Profile, note.profile_id)
    check_can_use(profile)
    appointment = _appointment(body, "booked")
    if (appointment.specialty, appointment.specialty_other) != (
        note.specialty,
        note.specialty_other,
    ):
        return _rewrite(db, note, account, oracle, request, appointment=appointment)
    with database_errors_retryable(db):
        db.refresh(note, with_for_update=True)
        details = (appointment.provider_name, appointment.appointment_date)
        if details == (note.provider_name, note.appointment_date):
            db.commit()
            return NotesResult(next="unchanged", notes=notes_out(db, note, account), message=None)
        date_changed = appointment.appointment_date != note.appointment_date
        note.provider_name, note.appointment_date = details
        if date_changed:
            reminders.schedule_appointment(db, account, profile, note)
        audit.record(
            db,
            "provider_notes.appointment_changed",
            actor_id=account.id,
            target_type="provider_note",
            target_id=note.id,
            request=request,
        )
        db.commit()
    return NotesResult(next="updated", notes=notes_out(db, note, account), message=None)


def refresh_notes(
    db: Session, note: ProviderNote, account: User, oracle: Oracle, request: Request
) -> NotesResult:
    """3.5's "When the Oracle updates the notes from the conversation": after the client asked
    for a change there ("Can you add a question about my iron levels?"), the notes are written
    again for the same appointment. Nothing is asked when nothing new was said."""
    return _rewrite(db, note, account, oracle, request, appointment=None)


def get_notes(db: Session, note: ProviderNote, account: User) -> ProviderNotesOut:
    return notes_out(db, note, account)


def _cards(db: Session, notes: list[ProviderNote], account: User) -> list[NotesCard]:
    """Upcoming appointments first, soonest first, then the rest, newest first (5.1)."""
    profiles: dict[uuid.UUID, Profile] = {}
    cards = []
    for note in notes:
        profile = profiles.setdefault(note.profile_id, db.get(Profile, note.profile_id))
        label = specialties.label(note.specialty, note.specialty_other)
        cards.append(
            NotesCard(
                id=note.id,
                conversation_id=note.conversation_id,
                title=_title(profile, account, label),
                specialty_label=label,
                provider_name=note.provider_name,
                appointment_date=note.appointment_date,
                upcoming=_upcoming(note.appointment_date),
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
        )
    upcoming = sorted((c for c in cards if c.upcoming), key=lambda c: c.appointment_date)
    others = sorted((c for c in cards if not c.upcoming), key=lambda c: c.created_at, reverse=True)
    return [*upcoming, *others]


def list_conversation_notes(
    db: Session, conversation: Conversation, account: User
) -> list[NotesCard]:
    notes = db.scalars(
        select(ProviderNote).where(ProviderNote.conversation_id == conversation.id)
    ).all()
    return _cards(db, list(notes), account)


def list_profile_notes(db: Session, profile: Profile, account: User) -> list[NotesCard]:
    """The profile's notes for My Visit Notes (5.1). Deleted conversations' notes aren't
    listed."""
    notes = db.scalars(
        select(ProviderNote)
        .join(Conversation, ProviderNote.conversation_id == Conversation.id)
        .where(
            ProviderNote.profile_id == profile.id,
            Conversation.profile_id == profile.id,
            Conversation.deleted_at.is_(None),
        )
    ).all()
    return _cards(db, list(notes), account)


def _notes_document(db: Session, note: ProviderNote, account: User) -> documents.Document:
    out = notes_out(db, note, account)
    header = out.header
    rows = [("First name", header.first_name)]
    if header.date_of_birth:
        rows.append(("Date of birth", documents.show_date(header.date_of_birth)))
    rows.append(("Specialty", header.specialty))
    if header.provider_name:
        rows.append(("Provider", header.provider_name))
    if header.appointment_date:
        rows.append(("Appointment date", documents.show_date(header.appointment_date)))
    if header.medical_advocate:
        rows.append(("Prepared by", f"{header.medical_advocate}, medical advocate"))
    return documents.Document(
        title=out.title,
        subtitle=f"Created {documents.show_date(out.created_at.date())}",
        header=rows,
        intro_title=documents.WHAT_THIS_IS_TITLE,
        intro=out.what_this_is,
        sections=out.sections,
        disclosure=out.disclosure,
        disclaimer=out.disclaimer,
    )


def notes_text(db: Session, note: ProviderNote, account: User, request: Request) -> NotesText:
    """Copy text (3.5), locked during the trial."""
    _check_downloads_unlocked(account, NOTES_LOCKED)
    text = documents.to_text(_notes_document(db, note, account))
    with database_errors_retryable(db):
        audit.record(
            db,
            "provider_notes.copied",
            actor_id=account.id,
            target_type="provider_note",
            target_id=note.id,
            request=request,
        )
        db.commit()
    return NotesText(text=text, confirmation=NOTES_COPIED)


def notes_pdf(
    db: Session, note: ProviderNote, account: User, paper: Paper, request: Request
) -> tuple[bytes, str]:
    """Download PDF and Print (3.5), locked during the trial. Named with the first name, the
    specialty and the date: the appointment's when it's known, otherwise the day the notes
    were made. Returns (pdf, file name)."""
    _check_downloads_unlocked(account, NOTES_LOCKED)
    document = _notes_document(db, note, account)
    try:
        pdf = documents.to_pdf(document, paper)
    except Exception as error:
        logger.warning("Notes PDF failed: %s (notes %s)", type(error).__name__, note.id)
        raise AppError(503, "download_failed", NOTES_DOWNLOAD_FAILED) from None
    with database_errors_retryable(db):
        audit.record(
            db,
            "provider_notes.downloaded",
            actor_id=account.id,
            target_type="provider_note",
            target_id=note.id,
            request=request,
        )
        db.commit()
    profile = db.get(Profile, note.profile_id)
    day = note.appointment_date or note.created_at.date()
    name = documents.file_name(
        "Notes",
        _first_name(profile, account),
        specialties.label(note.specialty, note.specialty_other),
        documents.file_date(day),
    )
    return pdf, name
