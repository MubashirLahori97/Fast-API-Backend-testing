"""My Visit Notes (story 5.1) and logged provider visits (story 5.2)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.ages import today
from app.core.config import settings
from app.core.schemas import RequestBody, clean_line, clean_message, clean_name
from app.guidance import specialties
from app.guidance.schemas import ProviderNotesOut, SpecialtyOut
from app.oracle.contract import GenesisStatus, LabStatus, MedicineChangeKind, NextStepPriority

# Story 5.2's messages.
VISIT_DATE_MISSING = "Please add the date of your visit."
VISIT_DATE_IN_FUTURE = "That date hasn’t happened yet. Please choose the date of your visit."
REASON_MISSING = "Please tell me what you went in for."
SPECIALTY_MISSING = "Please choose what kind of provider you saw."
SPECIALTY_OTHER_MISSING = "Please tell me what kind of provider this was."
# Not in the stories (docs/decisions/phase-6-7-visits-wellness.md).
MEDICINE_CHANGE_MISSING = "Please choose what changed for this medicine."
TOO_LONG = "Please keep this to {limit} characters or fewer."

LAB_STATUS_LABELS: dict[str, str] = {"pending": "Pending", "drawn": "Drawn", "resulted": "Resulted"}
MEDICINE_CHANGE_LABELS: dict[str, str] = {
    "new": "New",
    "dose_increased": "Dose increased",
    "dose_decreased": "Dose decreased",
    "discontinued": "Discontinued",
    "continued": "Continued",
    "added": "Added",
}
PRIORITY_LABELS: dict[str, str] = {"routine": "Routine", "schedule": "Schedule", "urgent": "Urgent"}
# Not in the stories: 5.2 asks for the "Genesis Gold® or Sacred Seven® status" without options.
GENESIS_STATUS_LABELS: dict[str, str] = {
    "taking": "Taking it",
    "started": "Starting it",
    "stopped": "Stopped it",
    "not_taking": "Not taking it",
}


def short_text(value: str | None) -> str | None:
    """A name or a short write-in on one line (a provider, a lab, a medicine, a dose)."""
    if value is None:
        return None
    value = clean_line(value)
    if len(value) > settings.name_max_length:
        raise ValueError(TOO_LONG.format(limit=settings.name_max_length))
    return value or None


def long_text(value: str | None) -> str | None:
    """Free text, line breaks kept (what they took away, their own notes)."""
    return clean_message(value) or None if value is not None else None


# Logging a visit (story 5.2)


class LabIn(RequestBody):
    """A row of "Labs ordered". A lab the notes requested that the provider didn't order is
    sent with `ordered` false (5.2: "the Client leaves them unmarked"). Rows with no name are
    left out."""

    name: str | None = None
    ordered: bool = True
    ordered_by: str | None = None
    status: LabStatus | None = None
    from_notes: bool = False  # listed from the provider-ready notes' requested labs

    _short = field_validator("name", "ordered_by")(short_text)


class MedicineChangeIn(RequestBody):
    """A row of "Changes in prescriptions or supplements". Rows with no name are left out."""

    name: str | None = None
    change: MedicineChangeKind | None = None
    new_dose: str | None = None

    _short = field_validator("name", "new_dose")(short_text)

    @field_validator("change")
    @classmethod
    def check_change(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None and info.data.get("name"):
            raise ValueError(MEDICINE_CHANGE_MISSING)
        return value


class NextStepIn(RequestBody):
    """A row of "Next steps". Rows with no text are left out."""

    text: str | None = None
    priority: NextStepPriority = "routine"

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str | None) -> str | None:
        return clean_line(value) or None if value is not None else None


class VisitLogIn(RequestBody):
    """Story 5.2's Log your visit form, which follows the Provider Visit Summary template.
    Visit date, why you went and the specialty are mandatory; everything else is optional.
    There's no upload. Sent whole on every save: an edit replaces the log's fields."""

    visit_date: date | None = None
    reason: str | None = None  # why you went: what they wanted help with
    duration: str | None = None  # how long it's been going on
    specialty: str | None = None  # a code from GET /provider-notes/specialties
    specialty_other: str | None = None  # with "other": the kind of provider
    provider_name: str | None = None
    practice: str | None = None
    follow_up_date: date | None = None
    diagnosis: str | None = None
    understanding: str | None = None
    unaddressed_concerns: str | None = None
    labs: list[LabIn] = Field(default_factory=list, max_length=settings.visit_log_max_rows)
    medicine_changes: list[MedicineChangeIn] = Field(
        default_factory=list, max_length=settings.visit_log_max_rows
    )
    # Adults only: left out (and ignored) for teens and children.
    genesis_gold_status: GenesisStatus | None = None
    sacred_seven_status: GenesisStatus | None = None
    next_steps: list[NextStepIn] = Field(
        default_factory=list, max_length=settings.visit_log_max_rows
    )
    own_notes: str | None = None

    @field_validator("visit_date")
    @classmethod
    def check_visit_date(cls, value: date | None) -> date:
        if value is None:
            raise ValueError(VISIT_DATE_MISSING)
        # The UTC date is ahead of every US state's, so no client's today is refused.
        if value > today():
            raise ValueError(VISIT_DATE_IN_FUTURE)
        return value

    @field_validator("reason")
    @classmethod
    def check_reason(cls, value: str | None) -> str:
        cleaned = long_text(value)
        if not cleaned:
            raise ValueError(REASON_MISSING)
        return cleaned

    @field_validator("specialty")
    @classmethod
    def check_specialty(cls, value: str | None) -> str:
        code = (value or "").strip()
        if code != specialties.OTHER and code not in specialties.options():
            raise ValueError(SPECIALTY_MISSING)
        return code

    @field_validator("specialty_other")
    @classmethod
    def check_specialty_other(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("specialty") != specialties.OTHER:
            return None
        cleaned = clean_name(value or "")
        if not cleaned:
            raise ValueError(SPECIALTY_OTHER_MISSING)
        return cleaned

    _short = field_validator("duration", "provider_name", "practice")(short_text)
    _long = field_validator("diagnosis", "understanding", "unaddressed_concerns", "own_notes")(
        long_text
    )


class CreateVisitLog(VisitLogIn):
    """A new log. `provider_notes_id` links it to a set of provider-ready notes (Log visit on a
    note card, or the post-visit notification); without it, it's a standalone visit (+ Log a
    visit). The app makes `client_request_id` once and sends it again with any retry, so the
    visit is never logged twice."""

    client_request_id: uuid.UUID
    provider_notes_id: uuid.UUID | None = None


class OptionOut(BaseModel):
    code: str
    label: str


class LabOut(BaseModel):
    name: str
    ordered: bool
    ordered_by: str | None = None
    status: LabStatus | None = None
    from_notes: bool = False


class MedicineChangeOut(BaseModel):
    name: str
    change: MedicineChangeKind
    new_dose: str | None = None


class NextStepOut(BaseModel):
    text: str
    priority: NextStepPriority


class VisitLogForm(BaseModel):
    """Log your visit, pre-filled (5.2). For notes: the specialty, provider name, visit date
    (the appointment's), the reason and the requested labs, with the notes themselves to show
    read-only. Standalone: only the first name and date of birth."""

    profile_id: uuid.UUID
    provider_notes_id: uuid.UUID | None
    first_name: str
    date_of_birth: date | None
    visit_date: date | None
    reason: str | None
    specialty: str | None
    specialty_other: str | None
    provider_name: str | None
    labs: list[LabOut]
    # "The Oracle’s notes for this visit are shown, read-only, as a reminder".
    notes: ProviderNotesOut | None
    # Adults only: teens and children don't see the Genesis Gold® and Sacred Seven® field.
    show_genesis_status: bool
    specialties: list[SpecialtyOut]
    lab_statuses: list[OptionOut]
    medicine_changes: list[OptionOut]
    priorities: list[OptionOut]
    genesis_statuses: list[OptionOut]
    # Shown when the client closes the form without saving.
    leave_confirmation: str


class MedicineLinkOut(BaseModel):
    name: str
    url: str  # its Drugs.com page


class VisitReviewOut(BaseModel):
    """What the Oracle made of the visit (5.2). `pending` until it's done, a few seconds after
    a save; `failed` while it's being tried again."""

    status: Literal["pending", "ready", "failed"]
    questions_answered: list[str] = []
    labs_ordered: list[str] = []
    missed: list[str] = []  # questions not answered, labs not ordered, concerns not raised
    new_medicines: list[MedicineLinkOut] = []
    # 5.2's "[Medicine] can interact with [existing medicine], so please check with your
    # pharmacist or provider."
    interactions: list[str] = []
    # Medicine changes it proposed for the health profile, waiting for the client to confirm
    # them (GET /profiles/{id}/health-facts).
    profile_updates_proposed: int = 0


class VisitLogOut(BaseModel):
    """A logged visit (5.2). It stays in the app: there's no download."""

    id: uuid.UUID
    profile_id: uuid.UUID
    # The notes it was logged for, while they can be opened.
    provider_notes_id: uuid.UUID | None
    title: str  # e.g. "Cardiology visit"
    visit_date: date
    reason: str
    duration: str | None
    specialty: str
    specialty_other: str | None
    specialty_label: str
    provider_name: str | None
    practice: str | None
    follow_up_date: date | None
    diagnosis: str | None
    understanding: str | None
    unaddressed_concerns: str | None
    labs: list[LabOut]
    medicine_changes: list[MedicineChangeOut]
    show_genesis_status: bool
    genesis_gold_status: GenesisStatus | None
    sacred_seven_status: GenesisStatus | None
    next_steps: list[NextStepOut]
    own_notes: str | None
    review: VisitReviewOut
    # A next step marked Urgent: 5.2's "You marked this as urgent...".
    urgent_reminder: str | None
    # Ask the Oracle: the first message of a conversation about the visit.
    ask_prompt: str
    can_download: bool = False
    # Delete visit log: the confirmation, and when the visit added Wellness Plan items, how
    # many and the keep-or-remove question (DELETE ...?plan_items=keep|remove).
    delete_confirmation: str
    plan_items_added: int
    plan_items_question: str | None
    created_at: datetime
    updated_at: datetime


class VisitLogSaved(BaseModel):
    visit_log: VisitLogOut
    # 5.2: "Would you like to talk about what your provider said?" Yes starts a conversation
    # with visit_log.ask_prompt.
    talk_it_through: str
    urgent_reminder: str | None


# My Visit Notes (story 5.1)


class VisitNotesSearch(RequestBody):
    """Search by title, topic, specialty or provider name. Sent in the body, never the URL:
    what someone searches for can be health information."""

    query: str = Field(default="", max_length=settings.visit_notes_search_max_length)


class VisitNoteCard(BaseModel):
    """One card in My Visit Notes. `type` says which screen it opens:

    - guidance_summary: GET /conversations/{conversation_id}/guidance-summary (PDF there too);
    - provider_notes: GET /provider-notes/{id}, with Edit appointment, Download PDF, Print and
      Copy text. Not logged yet: `can_log_visit` (Log visit). Logged: `visit_log_id`, with Ask
      the Oracle (`ask_prompt`) and Edit;
    - visit_log: a standalone visit, GET /visit-logs/{id}, with Ask the Oracle and Edit. No
      download."""

    type: Literal["guidance_summary", "provider_notes", "visit_log"]
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    title: str
    preview: str
    created_at: datetime  # the date shown on the card
    topic: str | None
    specialty_label: str | None
    provider_name: str | None
    appointment_date: date | None
    visit_date: date | None
    upcoming: bool
    upcoming_label: str | None  # "Upcoming · Cardiology · 14 Nov"
    visit_log_id: uuid.UUID | None
    can_log_visit: bool
    can_download: bool
    ask_prompt: str | None


class VisitNotesOut(BaseModel):
    """Upcoming appointments first, soonest first, then everything else, newest first.
    `message` is 5.1's "No notes yet" (with a prompt to start a conversation) or "No search
    results"."""

    cards: list[VisitNoteCard]
    message: str | None


def options(labels: dict[str, str]) -> list[OptionOut]:
    return [OptionOut(code=code, label=label) for code, label in labels.items()]
