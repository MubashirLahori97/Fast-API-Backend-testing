"""Data Deletion Requests (Super Admin and Admin story 5.2)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.ages import today
from app.core.config import settings
from app.core.schemas import RequestBody, clean_message

# Account Deletion, Family Member Deletion, Invited Teen Removal, Teen Deletion (5.2).
DeletionKind = Literal["account", "family_member", "teen_removal", "teen"]
DeletionSource = Literal["in_app", "by_email"]
# grace_period is 5.2's "Grace period", pending its "Pending review"; declined is the team
# turning a request down.
DeletionStatus = Literal[
    "grace_period", "pending", "in_progress", "on_legal_hold", "completed", "declined"
]

TEEN_NOT_SELECTED = "Please select the teen’s account."
DATE_EMPTY = "Please add the date the email was received."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
DATE_IN_FUTURE = "The date the email was received can’t be in the future."
IDENTITY_NOT_CONFIRMED = (
    "Please confirm the email came from the address registered to the teen’s account."
)


class ClientRef(BaseModel):
    id: uuid.UUID
    first_name: str
    email: str
    account_type: Literal["adult", "teen"]


class ProfileRef(BaseModel):
    id: uuid.UUID
    first_name: str | None
    is_self: bool


class DeletionRow(BaseModel):
    id: uuid.UUID
    kind: DeletionKind
    source: DeletionSource
    status: DeletionStatus
    client: ClientRef | None  # None once the account itself has been deleted
    profile: ProfileRef | None  # the family member
    received_at: datetime
    # 10 days after the request; null for a teen's request by email (no grace period).
    grace_ends_at: datetime | None
    # Deletion due: 45 calendar days after the request (or after the email was received).
    due_at: datetime
    days_left: int  # calendar days; negative once overdue
    highlighted: bool  # open, not on legal hold, and due within 5 days


class DeletionPage(BaseModel):
    items: list[DeletionRow]
    total: int
    message: str | None = None  # "There are no deletion requests right now."


class AffectedProfile(BaseModel):
    id: uuid.UUID
    first_name: str | None
    is_self: bool


class AffectedTeen(BaseModel):
    """An invited teen whose account and data go with an Account Deletion."""

    account_id: uuid.UUID
    first_name: str  # as the teen gave it on their own account


class WhatWillBeDeleted(BaseModel):
    # The account itself goes (Account Deletion, Invited Teen Removal, Teen Deletion).
    account_deleted: bool
    profiles: list[AffectedProfile]
    # Account Deletion: the invited teens' accounts and data (11.4, 6 Nov 19:22).
    invited_teens: list[AffectedTeen] = []
    # A Family Member Deletion: the account and its subscription stay.
    subscription_kept: bool


class Checklist(BaseModel):
    identity_confirmed: bool
    legal_hold_checked: bool
    # What "identity confirmed" means for this request's source.
    identity_check: str


class PersonRef(BaseModel):
    id: uuid.UUID
    first_name: str | None


class DeletionDetail(DeletionRow):
    what_will_be_deleted: WhatWillBeDeleted
    checklist: Checklist
    internal_notes: str | None
    legal_hold_note: str | None
    legal_hold_at: datetime | None
    email_received_on: date | None
    created_by: PersonRef | None  # requests the team created from an email
    completed_by: PersonRef | None
    completed_at: datetime | None
    purged_at: datetime | None
    complete_confirmation: str  # "Permanently delete this data? This can’t be undone."
    # While in its grace period, Complete deletion isn't available: "This request can be
    # completed after the grace period ends on [date]."
    grace_period_message: str | None = None


def _clean_text(value: object) -> object:
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
        return _clean_text(value)


class LegalHoldBody(RequestBody):
    note: str | None = Field(default=None, max_length=settings.admin_note_max_length * 2)

    @field_validator("note", mode="before")
    @classmethod
    def check_note(cls, value: object) -> object:
        return _clean_text(value)


class ChecklistBody(RequestBody):
    identity_confirmed: bool = False
    legal_hold_checked: bool = False


class CreateTeenDeletionBody(RequestBody):
    """+ Create deletion request, for a teen who can't sign in at all and emailed the team."""

    teen_account_id: uuid.UUID | None = None
    email_received_on: date | None = None
    # The identity check: the email came from the address registered to the teen's account.
    email_from_registered_address: bool = False
    note: str | None = Field(default=None, max_length=settings.admin_note_max_length * 2)

    @field_validator("teen_account_id", mode="before")
    @classmethod
    def check_teen(cls, value: object) -> object:
        if value in (None, ""):
            raise ValueError(TEEN_NOT_SELECTED)
        return value

    @field_validator("email_received_on", mode="before")
    @classmethod
    def check_date(cls, value: object) -> object:
        if value in (None, ""):
            raise ValueError(DATE_EMPTY)
        return value

    @field_validator("email_received_on")
    @classmethod
    def check_not_future(cls, value: date) -> date:
        if value > today():  # the UTC date, never behind the US date
            raise ValueError(DATE_IN_FUTURE)
        return value

    @field_validator("email_from_registered_address")
    @classmethod
    def check_identity(cls, value: bool) -> bool:
        if not value:
            raise ValueError(IDENTITY_NOT_CONFIRMED)
        return value

    @field_validator("note", mode="before")
    @classmethod
    def check_note(cls, value: object) -> object:
        return _clean_text(value)


class DeletionCreated(BaseModel):
    deletion_request: DeletionDetail
    message: str  # "The deletion request has been created. It’s due by [date]."
