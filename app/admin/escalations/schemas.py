"""Escalation Management (Super Admin and Admin story 4.1). The details show only what's needed
to review the escalation (BAA, minimum necessary): the triggering message and the Oracle's
one-line reason, never the rest of the conversation."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.conversations.schemas import EscalationLevel, SafetyOption
from app.core.config import settings
from app.core.schemas import RequestBody, clean_message

ReviewStatus = Literal["not_reviewed", "reviewed"]
# "teen": a teen with their own account (story 1.5).
ProfileType = Literal["self", "family_member", "teen"]


class ClientRef(BaseModel):
    id: uuid.UUID
    first_name: str
    email: str


class EscalationProfile(BaseModel):
    """Who it's about: the client, a family member (with the advocate's name), or a teen."""

    id: uuid.UUID
    type: ProfileType
    first_name: str | None
    advocate_first_name: str | None = None  # family members only


class EscalationRow(BaseModel):
    id: uuid.UUID
    level: EscalationLevel
    status: ReviewStatus
    client: ClientRef | None  # None once the account has been deleted
    profile: EscalationProfile
    reason: str | None  # the Oracle's one-line reason, while the message still exists
    detected_at: datetime


class EscalationPage(BaseModel):
    items: list[EscalationRow]
    total: int
    message: str | None = None  # "There are no escalations to review."


class ReviewerRef(BaseModel):
    id: uuid.UUID
    first_name: str | None


class EscalationDetail(EscalationRow):
    conversation_id: uuid.UUID
    # Why it escalated: the triggering message (null once deleted) and the Oracle's reason.
    triggering_message: str | None
    # What the Oracle showed: the story's advice (911, 988, Poison Control or the local number).
    oracle_showed: str | None
    outside_us: bool
    poison_control: bool
    # What the client chose, for an emergency or crisis: "No response" when nothing was picked.
    client_choice: SafetyOption | None
    client_choice_label: str | None
    chosen_at: datetime | None
    # Teens with their own account only: when the parent was told (story 3.2), or None.
    parent_told_at: datetime | None = None
    review_notes: str | None
    reviewed_by: ReviewerRef | None
    reviewed_at: datetime | None


def _check_notes(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = clean_message(value)
    if len(value) > settings.admin_note_max_length:
        raise ValueError(
            f"Please keep the notes to {settings.admin_note_max_length:,} characters or fewer."
        )
    return value or None


class NotesBody(RequestBody):
    notes: str | None = Field(default=None, max_length=settings.admin_note_max_length * 2)

    @field_validator("notes", mode="before")
    @classmethod
    def check_notes(cls, value: object) -> object:
        return _check_notes(value)


class ReviewBody(RequestBody):
    """Mark as reviewed (with any notes), or mark it Not yet reviewed again. Notes left out are
    kept as they are."""

    status: ReviewStatus
    notes: str | None = Field(default=None, max_length=settings.admin_note_max_length * 2)

    @field_validator("notes", mode="before")
    @classmethod
    def check_notes(cls, value: object) -> object:
        return _check_notes(value)


class ReviewOut(BaseModel):
    escalation: EscalationDetail
    message: str
