"""Logging provider visits (story 5.2).

A visit is logged from a set of provider-ready notes (Log visit, the post-visit notification)
or on its own (+ Log a visit). Saving is quick and needs no Oracle: the log is saved with
everything that follows it queued in the same transaction, so nothing is lost:

- the Oracle's review (`visits.review` job, app/visits/jobs.py): the comparison with the notes,
  Drugs.com links and interactions for new medicines, and the medicine changes proposed for
  the health profile as pending facts the client confirms (never saved without asking);
- the Wellness Plan update (7.1, app/wellness/triggers.py);
- the lab results reminder, and, for a new log, the health profile review notice (6.1).

Logging, viewing, editing and deleting are locked during the free trial (My Visit Notes is
greyed out). The log is health data: never logged, and its audit events hold ids only. The
decisions are in docs/decisions/phase-6-7-visits-wellness.md.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.conversations.models import Conversation
from app.core import audit, jobs
from app.core.ages import is_adult
from app.core.config import settings
from app.core.errors import AppError
from app.core.schemas import clean_line
from app.guidance import documents, specialties
from app.guidance import reminders as guidance_reminders
from app.guidance import service as guidance
from app.guidance.models import ProviderNote, ProviderNoteVersion
from app.health import reminders as health_reminders
from app.health import service as health
from app.notifications import service as notifications
from app.oracle import contract
from app.oracle.contract import Oracle, OracleError
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.visits.models import VisitLog
from app.visits.schemas import (
    GENESIS_STATUS_LABELS,
    LAB_STATUS_LABELS,
    MEDICINE_CHANGE_LABELS,
    PRIORITY_LABELS,
    CreateVisitLog,
    LabOut,
    MedicineChangeOut,
    MedicineLinkOut,
    NextStepOut,
    VisitLogForm,
    VisitLogIn,
    VisitLogOut,
    VisitLogSaved,
    VisitReviewOut,
    options,
)
from app.wellness import service as wellness
from app.wellness import triggers as wellness_triggers
from app.wellness.context import oracle_context

logger = logging.getLogger(__name__)

REVIEW_JOB = "visits.review"  # see app/visits/jobs.py
LAB_RESULTS = "lab_results_expected"  # the notifications kind (story 12.1)

# Story 5.1's and 5.2's messages.
NOTES_LOCKED = "My Visit Notes is part of your plan. Choose a plan to unlock it."
LOGGING_LOCKED = "Logging visits is part of your plan. Choose a plan to unlock it."
URGENT_REMINDER = "You marked this as urgent. Please make sure you follow up with your provider."
INTERACTION = (
    "{medicine} can interact with {existing}, so please check with your pharmacist or provider."
)
LEAVE_CONFIRMATION = "You have unsaved changes. Leave without saving?"
DELETE_CONFIRMATION = "Delete this visit log? This can’t be undone."
PLAN_ITEMS_QUESTION = (
    "This visit added {count} to your Wellness Plan. Keep them, or remove them too?"
)
TALK_IT_THROUGH = "Would you like to talk about what your provider said?"
SAVE_FAILED = "We couldn’t save your visit just now. Please try again."
DELETE_FAILED = "We couldn’t delete your visit log just now. Please try again."
# Not in the stories (docs/decisions/phase-6-7-visits-wellness.md).
VISIT_LOG_NOT_FOUND = "We couldn’t find that visit log."
ALREADY_LOGGED = "You’ve already logged this visit. You can edit it instead."
ASK_SELF = "I’d like to talk about my {specialty} visit on {date}."
ASK_FAMILY = "I’d like to talk about {name}’s {specialty} visit on {date}."

# Caps on what's kept from the Oracle's review.
LINE_MAX_LENGTH = 500
ITEMS_MAX = 20
URL_MAX_LENGTH = 2000
# The health profile questions a visit may propose changes to (5.2: medicine changes).
PROFILE_UPDATE_KEYS = frozenset({"medications", "supplements"})

# Once a note's visit is logged, its "How did it go?" and "Have you booked?" aren't needed.
FOLLOW_UPS_AFTER_LOGGING = (
    guidance_reminders.APPOINTMENT_FOLLOW_UP,
    guidance_reminders.BOOKING_FOLLOW_UP,
)

PlanItemsChoice = Literal["keep", "remove"]


def check_unlocked(account: User, message: str = LOGGING_LOCKED) -> None:
    """5.1 and 5.2: My Visit Notes and visit logging are greyed out during the free trial (and
    after a subscription ended), with the story's upgrade prompt."""
    if entitlements.feature_access(account)["visit_notes"]:
        raise AppError(403, "upgrade_required", message)


@contextmanager
def _failing_with(db: Session, code: str, message: str) -> Iterator[None]:
    """The story's "Save failed" or "Delete failed" for any database error. The error's own
    text isn't logged or returned: it can contain what the client typed."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, code, message) from None


def first_name(profile: Profile, account: User) -> str:
    return clean_line((account.first_name if profile.is_self else profile.first_name) or "")


def visit_log_not_found() -> AppError:
    return AppError(404, "visit_log_not_found", VISIT_LOG_NOT_FOUND)


def visible_note(db: Session, profile: Profile, note_id: uuid.UUID | None) -> ProviderNote | None:
    """The profile's notes, while they can be opened: their conversation isn't deleted."""
    if note_id is None:
        return None
    note = db.get(ProviderNote, note_id)
    if note is None or note.profile_id != profile.id:
        return None
    conversation = db.get(Conversation, note.conversation_id)
    if conversation is None or conversation.deleted_at is not None:
        return None
    return note


def _current_content(db: Session, note: ProviderNote) -> dict[str, Any]:
    version = db.scalar(
        select(ProviderNoteVersion).where(
            ProviderNoteVersion.note_id == note.id, ProviderNoteVersion.version == note.version
        )
    )
    return version.content if version is not None else {}


def log_for_note(db: Session, note: ProviderNote) -> VisitLog | None:
    return db.scalar(select(VisitLog).where(VisitLog.provider_note_id == note.id))


# Showing a log


def title(profile: Profile, account: User, specialty_label: str) -> str:
    """ "Cardiology visit", or "Azka’s Cardiology visit" for a family member."""
    if profile.is_self:
        return f"{specialty_label} visit"
    return f"{first_name(profile, account)}’s {specialty_label} visit"


def ask_prompt(profile: Profile, account: User, log: VisitLog) -> str:
    """Ask the Oracle on a logged visit: the first message of a conversation about it."""
    label = specialties.label(log.specialty, log.specialty_other)
    day = documents.show_date(log.visit_date)
    if profile.is_self:
        return ASK_SELF.format(specialty=label, date=day)
    return ASK_FAMILY.format(name=first_name(profile, account), specialty=label, date=day)


def _review_out(log: VisitLog) -> VisitReviewOut:
    if log.review_status != "ready" or log.review is None:
        return VisitReviewOut(status=log.review_status)
    review = log.review
    return VisitReviewOut(
        status="ready",
        questions_answered=review.get("questions_answered", []),
        labs_ordered=review.get("labs_ordered", []),
        missed=review.get("missed", []),
        new_medicines=[MedicineLinkOut(**link) for link in review.get("new_medicines", [])],
        interactions=[
            INTERACTION.format(medicine=pair["medicine"], existing=pair["existing_medicine"])
            for pair in review.get("interactions", [])
        ],
        profile_updates_proposed=review.get("profile_updates_proposed", 0),
    )


def _urgent(log: VisitLog) -> str | None:
    """5.2: "Next step marked Urgent: The Oracle reminds them to follow it up"."""
    return URGENT_REMINDER if any(s["priority"] == "urgent" for s in log.next_steps) else None


def _items_text(count: int) -> str:
    return "1 item" if count == 1 else f"{count} items"


def visit_log_out(db: Session, log: VisitLog, account: User) -> VisitLogOut:
    profile = db.get(Profile, log.profile_id)
    adult = is_adult(profile.date_of_birth) if profile.date_of_birth else True
    label = specialties.label(log.specialty, log.specialty_other)
    note = visible_note(db, profile, log.provider_note_id)
    added = wellness.items_added_by_visit(db, profile, log.id)
    return VisitLogOut(
        id=log.id,
        profile_id=log.profile_id,
        provider_notes_id=note.id if note else None,
        title=title(profile, account, label),
        visit_date=log.visit_date,
        reason=log.reason,
        duration=log.duration,
        specialty=log.specialty,
        specialty_other=log.specialty_other,
        specialty_label=label,
        provider_name=log.provider_name,
        practice=log.practice,
        follow_up_date=log.follow_up_date,
        diagnosis=log.diagnosis,
        understanding=log.understanding,
        unaddressed_concerns=log.unaddressed_concerns,
        labs=[LabOut(**lab) for lab in log.labs],
        medicine_changes=[MedicineChangeOut(**change) for change in log.medicine_changes],
        show_genesis_status=adult,
        genesis_gold_status=log.genesis_gold_status if adult else None,
        sacred_seven_status=log.sacred_seven_status if adult else None,
        next_steps=[NextStepOut(**step) for step in log.next_steps],
        own_notes=log.own_notes,
        review=_review_out(log),
        urgent_reminder=_urgent(log),
        ask_prompt=ask_prompt(profile, account, log),
        delete_confirmation=DELETE_CONFIRMATION,
        plan_items_added=added,
        plan_items_question=(
            PLAN_ITEMS_QUESTION.format(count=_items_text(added)) if added else None
        ),
        created_at=log.created_at,
        updated_at=log.updated_at,
    )


def get_visit_log(db: Session, log: VisitLog, account: User) -> VisitLogOut:
    check_unlocked(account, NOTES_LOCKED)
    return visit_log_out(db, log, account)


# The form


def _form(
    profile: Profile,
    account: User,
    *,
    note: ProviderNote | None = None,
    reason: str | None = None,
    labs: list[LabOut] | None = None,
    notes_out=None,
) -> VisitLogForm:
    adult = is_adult(profile.date_of_birth) if profile.date_of_birth else True
    visit_date = note.appointment_date if note else None
    if visit_date is not None and visit_date > datetime.now(UTC).date():
        visit_date = None  # logged before the appointment's date: the client enters it
    return VisitLogForm(
        profile_id=profile.id,
        provider_notes_id=note.id if note else None,
        first_name=first_name(profile, account),
        date_of_birth=profile.date_of_birth,
        visit_date=visit_date,
        reason=reason,
        specialty=note.specialty if note else None,
        specialty_other=note.specialty_other if note else None,
        provider_name=note.provider_name if note else None,
        labs=labs or [],
        notes=notes_out,
        show_genesis_status=adult,
        specialties=guidance.list_specialties(),
        lab_statuses=options(LAB_STATUS_LABELS),
        medicine_changes=options(MEDICINE_CHANGE_LABELS),
        priorities=options(PRIORITY_LABELS),
        genesis_statuses=options(GENESIS_STATUS_LABELS) if adult else [],
        leave_confirmation=LEAVE_CONFIRMATION,
    )


def standalone_form(profile: Profile, account: User) -> VisitLogForm:
    """+ Log a visit: only the first name and date of birth are known."""
    check_unlocked(account)
    check_can_use(profile)
    return _form(profile, account)


def notes_form(db: Session, note: ProviderNote, account: User) -> VisitLogForm:
    """Log visit on a set of notes: what the notes know, and the notes to show read-only."""
    check_unlocked(account)
    profile = db.get(Profile, note.profile_id)
    check_can_use(profile)
    if log_for_note(db, note) is not None:
        raise AppError(409, "visit_already_logged", ALREADY_LOGGED)
    content = _current_content(db, note)
    labs = [
        LabOut(name=lab["name"], ordered=False, from_notes=True)
        for lab in content.get("labs_requested") or []
    ]
    return _form(
        profile,
        account,
        note=note,
        reason=content.get("chief_complaint"),
        labs=labs,
        notes_out=guidance.notes_out(db, note, account),
    )


# Saving


def _fill(log: VisitLog, body: VisitLogIn, adult: bool) -> None:
    """Copies the form onto the log. Rows with no name or text are left out, and a lab that
    wasn't ordered keeps no status or orderer."""
    log.visit_date = body.visit_date
    log.reason = body.reason
    log.duration = body.duration
    log.specialty = body.specialty
    log.specialty_other = body.specialty_other
    log.provider_name = body.provider_name
    log.practice = body.practice
    log.follow_up_date = body.follow_up_date
    log.diagnosis = body.diagnosis
    log.understanding = body.understanding
    log.unaddressed_concerns = body.unaddressed_concerns
    log.labs = [
        {
            "name": lab.name,
            "ordered": lab.ordered,
            "ordered_by": lab.ordered_by if lab.ordered else None,
            "status": lab.status if lab.ordered else None,
            "from_notes": lab.from_notes,
        }
        for lab in body.labs
        if lab.name
    ]
    log.medicine_changes = [
        {"name": change.name, "change": change.change, "new_dose": change.new_dose}
        for change in body.medicine_changes
        if change.name
    ]
    # 5.2: teens and children don't get the Genesis Gold® and Sacred Seven® field.
    log.genesis_gold_status = body.genesis_gold_status if adult else None
    log.sacred_seven_status = body.sacred_seven_status if adult else None
    log.next_steps = [
        {"text": step.text, "priority": step.priority} for step in body.next_steps if step.text
    ]
    log.own_notes = body.own_notes


def _schedule_lab_reminder(db: Session, account: User, profile: Profile, log: VisitLog) -> None:
    """5.2: "it schedules a reminder for when results are expected", for labs ordered and not
    yet resulted, `lab_results_reminder_days` after the visit. Replaces the one scheduled
    before; none when that day has passed."""
    notifications.cancel_scheduled(db, account, kind=LAB_RESULTS, target_id=log.id)
    if not any(lab["ordered"] and lab["status"] != "resulted" for lab in log.labs):
        return
    day = log.visit_date + timedelta(days=settings.lab_results_reminder_days)
    run_at = datetime.combine(day, time(settings.appointment_reminder_hour_utc), tzinfo=UTC)
    if run_at > datetime.now(UTC):
        notifications.schedule(db, account, LAB_RESULTS, run_at, profile=profile, target_id=log.id)


def _after_save(
    db: Session,
    account: User,
    profile: Profile,
    log: VisitLog,
    request: Request,
    *,
    created: bool,
) -> None:
    """What every save sets going (5.2: "Changes go through the same steps as saving")."""
    jobs.enqueue(db, REVIEW_JOB, {"visit_log_id": str(log.id), "revision": log.revision})
    wellness_triggers.visit_saved(db, account, profile, log.id, log.revision, edited=not created)
    _schedule_lab_reminder(db, account, profile, log)
    details: dict[str, Any] = {"profile_id": str(profile.id), "revision": log.revision}
    if log.provider_note_id is not None:
        details["provider_note_id"] = str(log.provider_note_id)
    audit.record(
        db,
        "visit_log.created" if created else "visit_log.updated",
        actor_id=account.id,
        target_type="visit_log",
        target_id=log.id,
        request=request,
        details=details,
    )
    if created:
        # 6.1: "You’ve logged a visit. Has anything changed in your health profile?"
        health_reminders.visit_logged(db, account, profile)


def _saved(db: Session, log: VisitLog, account: User) -> VisitLogSaved:
    out = visit_log_out(db, log, account)
    return VisitLogSaved(
        visit_log=out, talk_it_through=TALK_IT_THROUGH, urgent_reminder=out.urgent_reminder
    )


def create_visit_log(
    db: Session, profile: Profile, body: CreateVisitLog, account: User, request: Request
) -> tuple[VisitLogSaved, bool]:
    """Saves a new log. Returns (saved, created); safe to repeat with the same
    client_request_id. A linked note's card then shows Ask the Oracle and Edit instead of Log
    visit, and its "How did it go?" follow-up isn't needed any more."""
    check_unlocked(account)
    with _failing_with(db, "save_failed", SAVE_FAILED):
        db.refresh(profile, with_for_update=True)  # one new log per profile at a time
        check_can_use(profile)
        existing = db.scalar(
            select(VisitLog).where(
                VisitLog.profile_id == profile.id,
                VisitLog.client_request_id == body.client_request_id,
            )
        )
        if existing is not None:
            db.commit()
            return _saved(db, existing, account), False
        note = None
        if body.provider_notes_id is not None:
            note = visible_note(db, profile, body.provider_notes_id)
            if note is None:
                raise AppError(404, "provider_notes_not_found", guidance.NOTES_NOT_FOUND)
            if log_for_note(db, note) is not None:
                raise AppError(409, "visit_already_logged", ALREADY_LOGGED)
        log = VisitLog(
            profile_id=profile.id,
            provider_note_id=note.id if note else None,
            client_request_id=body.client_request_id,
            revision=1,
            review_status="pending",
        )
        _fill(log, body, is_adult(profile.date_of_birth))
        db.add(log)
        db.flush()
        if note is not None:
            for kind in (
                guidance_reminders.APPOINTMENT_FOLLOW_UP,
                guidance_reminders.BOOKING_FOLLOW_UP,
            ):
                notifications.cancel_scheduled(db, account, kind=kind, target_id=note.id)
        _after_save(db, account, profile, log, request, created=True)
        db.commit()
    return _saved(db, log, account), True


def update_visit_log(
    db: Session, log: VisitLog, body: VisitLogIn, account: User, request: Request
) -> VisitLogSaved:
    """Edit (5.2): the form again, replacing the log's fields. The review, the plan update and
    the lab reminder run again for the new version."""
    check_unlocked(account)
    with _failing_with(db, "save_failed", SAVE_FAILED):
        db.refresh(log, with_for_update=True)
        profile = db.get(Profile, log.profile_id)
        check_can_use(profile)
        _fill(log, body, is_adult(profile.date_of_birth))
        log.revision += 1
        log.review_status = "pending"
        log.review = None
        log.reviewed_at = None
        _after_save(db, account, profile, log, request, created=False)
        db.commit()
    return _saved(db, log, account)


def delete_visit_log(
    db: Session,
    log: VisitLog,
    account: User,
    plan_items: PlanItemsChoice | None,
    request: Request,
) -> None:
    """Delete visit log (5.2), after the client confirmed. When the visit added items to the
    Wellness Plan, the client chooses to keep or remove them (409 until `plan_items` says).

    The row is deleted: a linked note goes back to "Not logged yet", a standalone card goes,
    and the Oracle no longer uses the visit. Medicine changes already saved to the health
    profile stay. Its reminders are cancelled, and the deletion is in the audit log (kept six
    years) with ids only."""
    check_unlocked(account)
    with _failing_with(db, "delete_failed", DELETE_FAILED):
        db.refresh(log, with_for_update=True)
        profile = db.get(Profile, log.profile_id)
        check_can_use(profile)
        added = wellness.items_added_by_visit(db, profile, log.id)
        if added and plan_items is None:
            raise AppError(
                409,
                "plan_items_choice_required",
                PLAN_ITEMS_QUESTION.format(count=_items_text(added)),
                "plan_items",
            )
        removed = 0
        if added and plan_items == "remove":
            removed = wellness.remove_items_added_by_visit(db, account, profile, log.id, request)
        notifications.cancel_scheduled(db, account, target_id=log.id)
        audit.record(
            db,
            "visit_log.deleted",
            actor_id=account.id,
            target_type="visit_log",
            target_id=log.id,
            request=request,
            details={
                "profile_id": str(profile.id),
                "plan_items_added": added,
                "plan_items_removed": removed,
            },
        )
        db.delete(log)
        db.commit()


# For the Oracle


def logged_visit(log: VisitLog, *, adult: bool) -> contract.LoggedVisit:
    """The visit as the Oracle gets it: no provider name or practice."""
    return contract.LoggedVisit(
        visit_date=log.visit_date,
        reason=log.reason,
        duration=log.duration,
        specialty=specialties.label(log.specialty, log.specialty_other),
        follow_up_date=log.follow_up_date,
        diagnosis=log.diagnosis,
        understanding=log.understanding,
        unaddressed_concerns=log.unaddressed_concerns,
        labs=[
            contract.VisitLab(
                name=lab["name"],
                ordered=lab["ordered"],
                ordered_by=lab.get("ordered_by"),
                status=lab.get("status"),
            )
            for lab in log.labs
        ],
        medicine_changes=[
            contract.MedicineChange(
                name=change["name"], change=change["change"], new_dose=change.get("new_dose")
            )
            for change in log.medicine_changes
        ],
        genesis_gold=log.genesis_gold_status if adult else None,
        sacred_seven=log.sacred_seven_status if adult else None,
        next_steps=[
            contract.NextStep(text=step["text"], priority=step["priority"])
            for step in log.next_steps
        ],
        own_notes=log.own_notes,
    )


def oracle_visits(db: Session, profile: Profile) -> tuple[contract.LoggedVisit, ...]:
    """The profile's latest logged visits, newest first, for ProfileContext.visits (the
    conversations package fills it in). A deleted log is gone, so it's never used again."""
    logs = db.scalars(
        select(VisitLog)
        .where(VisitLog.profile_id == profile.id)
        .order_by(VisitLog.visit_date.desc(), VisitLog.created_at.desc())
        .limit(settings.oracle_visit_logs)
    ).all()
    adult = is_adult(profile.date_of_birth) if profile.date_of_birth else True
    return tuple(logged_visit(log, adult=adult) for log in logs)


def _notes_for_oracle(
    db: Session, profile: Profile, log: VisitLog
) -> contract.ProviderNotes | None:
    note = visible_note(db, profile, log.provider_note_id)
    if note is None:
        return None
    content = _current_content(db, note)
    if not content:
        return None
    return contract.ProviderNotes(
        chief_complaint=content.get("chief_complaint") or "",
        clinical_context=content.get("clinical_context") or "",
        reported_lab_values=[
            contract.ReportedLabValue(test=lab["test"], value=lab["value"])
            for lab in content.get("reported_lab_values") or []
        ],
        labs_requested=[
            contract.RequestedLab(
                name=lab["name"], reason=lab.get("reason") or "", primary=lab.get("primary", True)
            )
            for lab in content.get("labs_requested") or []
        ],
        questions=list(content.get("questions") or []),
        medications=list(content.get("medications") or []),
        taking_genesis_gold=bool(content.get("taking_genesis_gold")),
        red_flags=list(content.get("red_flags") or []),
        recommendation=content.get("recommendation") or "",
        referral=content.get("referral"),
        mentions_products=bool(content.get("mentions_products")),
    )


def _line(value: object) -> str | None:
    return clean_line(value)[:LINE_MAX_LENGTH] or None if isinstance(value, str) else None


def _lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [line for value in values[:ITEMS_MAX] if (line := _line(value))]


def _drugs_com(url: object) -> str | None:
    """5.2 links new medicines to Drugs.com: only an https link to drugs.com is kept."""
    if not isinstance(url, str) or len(url) > URL_MAX_LENGTH or url != clean_line(url):
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "drugs.com" or host.endswith(".drugs.com")):
        return None
    return url


def _clean_review(result: object) -> tuple[dict[str, Any], list[contract.ProposedAnswer]]:
    """The review as it's stored, and the health profile changes it proposes (medicines and
    supplements only)."""
    if not isinstance(result, contract.VisitReview):
        raise OracleError("The review isn't a VisitReview.")
    links = []
    for link in (result.new_medicines or [])[:ITEMS_MAX]:
        if isinstance(link, contract.MedicineLink):
            name, url = _line(link.name), _drugs_com(link.url)
            if name and url:
                links.append({"name": name, "url": url})
    interactions = []
    for pair in (result.interactions or [])[:ITEMS_MAX]:
        if isinstance(pair, contract.MedicineInteraction):
            medicine, existing = _line(pair.medicine), _line(pair.existing_medicine)
            if medicine and existing:
                interactions.append({"medicine": medicine, "existing_medicine": existing})
    updates = [
        answer
        for answer in (result.profile_updates or [])[:ITEMS_MAX]
        if isinstance(answer, contract.ProposedAnswer)
        and answer.question_key in PROFILE_UPDATE_KEYS
    ]
    review = {
        "questions_answered": _lines(result.questions_answered),
        "labs_ordered": _lines(result.labs_ordered),
        "missed": _lines(result.missed),
        "new_medicines": links,
        "interactions": interactions,
    }
    return review, updates


def review_visit(db: Session, payload: dict[str, Any], oracle: Oracle) -> None:
    """The visits.review job: the Oracle's review of one save of a log. Does nothing when the
    log was deleted or saved again since (that save has its own job). The Oracle is asked with
    no transaction or lock held. A failure marks the review failed and raises, so the worker
    tries again. The worker commits."""
    log_id = uuid.UUID(payload["visit_log_id"])
    revision = payload["revision"]
    log = db.get(VisitLog, log_id)
    if log is None or log.revision != revision:
        return
    profile = db.get(Profile, log.profile_id)
    account = db.get(User, profile.account_id)
    try:
        check_can_use(profile)
    except AppError:
        return  # turned off or being deleted: nothing more is done with it
    adult = is_adult(profile.date_of_birth)
    context = oracle_context(db, profile, account)
    visit = logged_visit(log, adult=adult)
    notes = _notes_for_oracle(db, profile, log)
    db.commit()

    try:
        review, updates = _clean_review(oracle.review_visit(context, visit, notes))
    except Exception as error:  # the AI service failed, or answered something unusable
        logger.warning("Visit review failed: %s (visit log %s)", type(error).__name__, log_id)
        db.rollback()
        db.execute(
            update(VisitLog)
            .where(VisitLog.id == log_id, VisitLog.revision == revision)
            .values(review_status="failed")
        )
        db.commit()
        raise OracleError("The visit review failed.") from None

    log = db.scalar(select(VisitLog).where(VisitLog.id == log_id).with_for_update())
    if log is None or log.revision != revision:
        return
    # 5.2: "it asks before adding medicine changes to the health profile": pending facts,
    # which the client confirms or discards (GET /profiles/{id}/health-facts).
    proposed = 0
    for answer in updates:
        fact = health.propose_fact(
            db, profile, account, answer.question_key, answer.value, answer.other
        )
        proposed += fact is not None
    review["profile_updates_proposed"] = proposed
    log.review = review
    log.review_status = "ready"
    log.reviewed_at = datetime.now(UTC)
