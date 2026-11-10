"""Guidance summaries (story 3.3) and provider-ready notes (stories 3.4 and 3.5).

Summaries and notes are sent as ordered sections, so the apps, the copied text and the PDF all
show them in the stories' order, from one place (app/guidance/documents.py).
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.conversations.schemas import MessageOut
from app.core.schemas import RequestBody

Paper = Literal["letter", "a4"]


class SectionItemOut(BaseModel):
    """One line of a section: a question, a test, a step, a product, a medication."""

    text: str
    detail: str | None = None  # why a test matters, a lab's reason, why a product is suggested
    # Recommendations: the store or partner page. Tests Worth Discussing: the link Deborah
    # supplied for the test, an information link (nothing is ordered through the app).
    url: str | None = None
    # What You Can Do Now: the Wellness Protocols library section to link to (story 7.1).
    protocol: str | None = None
    # Recommendations: genesis_product | partner_product | medicine | test | other.
    # Labs I am requesting: primary | also_request. Clinical context: reported_lab.
    kind: str | None = None
    # Recommendations, Genesis products: "How to take it (from the label): 4 g per 50 lb of
    # body weight, daily." (3.3), the label's directions word for word.
    directions: str | None = None


class SectionOut(BaseModel):
    key: str  # e.g. "what_im_hearing", "chief_complaint"
    title: str  # e.g. "What I’m Hearing", "1. Chief complaint"
    text: str | None = None
    items: list[SectionItemOut] = []
    # A fixed note shown with the section: 3.3's product note under Recommendations, 3.4's
    # Genesis Gold® note under medications.
    note: str | None = None


# Guidance summaries (story 3.3)


class AddedDetailOut(BaseModel):
    """Something the Oracle saved to the health profile from this conversation."""

    question_key: str
    question: str  # worded for the profile, e.g. "Is Azka taking any medications?"
    answer: str  # in words
    added_at: datetime  # "Added from our conversation on [date]" (6.1)


class AddedToHealthProfileOut(BaseModel):
    """3.3's list below the summary: what was saved automatically from this conversation (the
    client accepted the Health Consent), with the disclaimer above it and a Review in My
    Health button. Not sent when nothing was added."""

    # "Here’s what I’ve added to your health profile from our conversation. If anything isn’t
    # right, you can change or remove it in My Health."
    message: str
    details: list[AddedDetailOut]
    # Review in My Health. False during the free trial (My Health is greyed out): tapping it
    # shows `review_locked_message` with the upgrade prompt.
    can_review: bool
    review_locked_message: str | None


class GuidanceSummaryOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    profile_id: uuid.UUID
    stage: Literal["first_look", "full"]  # first_look: shared early, completed later
    # 3.3's "Thank you for sharing all of that. Here’s what I’m seeing." (full summaries).
    introduction: str
    # In 3.3's order, empty ones left out: no Hypothalamic Connection without a clear link,
    # and Recommendations only for adults with products to suggest, never during an emergency
    # or crisis hold (story 3.2).
    sections: list[SectionOut]
    # The one disclosure box, at the very end, when products or links were recommended: 3.3's
    # "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®,
    # Sacred Seven® and Gen-Pro®."
    disclosure: str | None
    disclaimer: str  # every summary ends with it
    # Below the summary: what was added to the health profile from this conversation; null
    # when nothing was (3.3).
    added_to_health_profile: AddedToHealthProfileOut | None
    # A provider visit is relevant: offer "Create notes for my provider" (story 3.4).
    offer_provider_notes: bool
    # Download Summary (PDF). False during the free trial: show `locked_message` with the
    # upgrade prompt instead.
    can_download: bool
    locked_message: str | None
    shared_at: datetime
    updated_at: datetime


class SummaryCard(BaseModel):
    """A summary in the profile's list (My Visit Notes, story 5.1)."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    topic: str | None  # the conversation's
    stage: Literal["first_look", "full"]
    preview: str  # the start of What I’m Hearing
    shared_at: datetime
    updated_at: datetime


# Provider-ready notes (stories 3.4 and 3.5)


class SpecialtyOut(BaseModel):
    code: str
    label: str


class AppointmentIn(RequestBody):
    """Story 3.4's appointment card. `specialty` is a code from GET /provider-notes/specialties;
    "other" needs `specialty_other`, the kind of provider in the client's words. The provider's
    name and the date are optional; leaving one out clears it."""

    specialty: str | None = None
    specialty_other: str | None = None
    provider_name: str | None = None
    appointment_date: date | None = None


class CreateProviderNotes(AppointmentIn):
    """Create my notes (story 3.4). The app makes `client_request_id` once and sends it again
    with any retry, so the notes are never made twice.

    `booking` is the answer to "Have you booked an appointment with a provider?":
    - "booked": the card (filled in from what the client mentioned, in Scenario A);
    - "not_yet": the specialty the Oracle suggested (its appointment card widget), with no
      provider or date;
    - "skip": no details; the notes are for a primary care provider."""

    client_request_id: uuid.UUID
    booking: Literal["booked", "not_yet", "skip"] = "booked"


class AppointmentOut(BaseModel):
    specialty: str  # the code
    specialty_other: str | None
    specialty_label: str  # e.g. "Cardiology", or the write-in
    provider_name: str | None
    appointment_date: date | None
    # The date is today or later: 5.1 lists these first, with an Upcoming label.
    upcoming: bool


class NotesHeaderOut(BaseModel):
    """The notes' header (story 3.4), filled in by the backend: the first name only, the date
    of birth (the Oracle never gets it), and the appointment details that are known."""

    first_name: str
    date_of_birth: date | None
    specialty: str
    provider_name: str | None
    appointment_date: date | None
    # A family member's notes: the client, as medical advocate.
    medical_advocate: str | None


class ProviderNotesOut(BaseModel):
    """The notes screen (story 3.5): always the latest version."""

    id: uuid.UUID
    conversation_id: uuid.UUID  # for Back to conversation
    profile_id: uuid.UUID
    title: str  # e.g. "Notes for my Cardiology appointment"
    created_at: datetime
    updated_at: datetime  # when the content was last written
    version: int
    appointment: AppointmentOut  # with the Edit appointment button
    header: NotesHeaderOut
    what_this_is: str
    sections: list[SectionOut]  # the template's sections, in order
    disclosure: str | None  # only when Genesis products or affiliate links are mentioned
    disclaimer: str
    # Download PDF, Print and Copy text. False during the free trial: show `locked_message`
    # with the upgrade prompt instead.
    can_download: bool
    locked_message: str | None


class NotesCard(BaseModel):
    """A set of notes in a list (the conversation's, or the profile's for My Visit Notes)."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    title: str
    specialty_label: str
    provider_name: str | None
    appointment_date: date | None
    upcoming: bool
    created_at: datetime
    updated_at: datetime


class NotesResult(BaseModel):
    """What happened, and what the app shows next:

    - "ready": the notes were created or rewritten; `message` is the Oracle's line added to
      the conversation ("Your notes are ready...", "I’ve updated your notes for...");
    - "updated": the provider's name or the date changed (no new content, no new line);
    - "unchanged": nothing to change (a create sent again, or no new messages to add);
    - "more_questions": the Oracle needs a few more answers first; `message` is its question,
      added to the conversation;
    - "clarify_specialty": it can't tell what an "Other" specialty is; `message` asks, and the
      app opens the card again."""

    next: Literal["ready", "updated", "unchanged", "more_questions", "clarify_specialty"]
    notes: ProviderNotesOut | None
    message: MessageOut | None


class NotesText(BaseModel):
    """Copy text (story 3.5): the full notes as plain text, with the disclaimer and, when
    relevant, the disclosure box."""

    text: str
    confirmation: str  # "Your notes have been copied."
