"""Support and consultation requests (story 10.1), and the support team's view of them
(Super Admin story 5.1)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_message

# email_change: story 11.1's Email Change Request, made from Profile & Account (accounts package).
Kind = Literal["talk_to_support", "consultation", "knowledge_gap", "email_change"]
FormKind = Literal["talk_to_support", "consultation"]
ConversationKind = Literal["talk_to_support", "knowledge_gap"]
Status = Literal["open", "resolved"]
AccountType = Literal["adult", "teen"]

MESSAGE_EMPTY = "Please tell us how we can help."


class SupportRequestBody(RequestBody):
    """The Contact support team form ("How can we help?", kind talk_to_support) or the Consult
    with support team form ("What would you like help with?", kind consultation). The app makes
    `client_request_id` (a UUID) once per request and sends it again with any retry, including
    a request it kept while offline, so a request is never sent twice."""

    client_request_id: uuid.UUID
    kind: FormKind
    message: str = Field(default="", max_length=settings.support_message_max_length)

    @field_validator("message", mode="before")
    @classmethod
    def check_message(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = clean_message(value)
        if not value:
            raise ValueError(MESSAGE_EMPTY)
        if len(value) > settings.support_message_max_length:
            raise ValueError(
                f"That message is too long. Please keep it to "
                f"{settings.support_message_max_length:,} characters or fewer."
            )
        return value


class SupportRequestSent(BaseModel):
    """A request the team has received. `message` is the confirmation to show the client."""

    id: uuid.UUID
    kind: Kind
    status: Status
    profile_id: uuid.UUID | None  # the profile it's about, if any
    created_at: datetime
    message: str


# The support team's view (Phase A's admin endpoints return these).


class ClientOut(BaseModel):
    id: uuid.UUID
    first_name: str
    email: str
    account_type: AccountType


class AboutProfile(BaseModel):
    """The profile a request is about, for "Sent by Sarah about Azka"."""

    id: uuid.UUID
    is_self: bool  # the client's own profile
    first_name: str | None  # null for a family draft that has no name yet
    relationship: str | None  # family members: parent | child | partner | someone_else


class SupportRequestSummary(BaseModel):
    """A row in the team's list."""

    id: uuid.UUID
    kind: Kind
    status: Status
    client: ClientOut
    profile: AboutProfile | None
    first_line: str
    received_at: datetime


class SupportRequestDetail(SupportRequestSummary):
    # The full message: what the client wrote, or for a knowledge gap the question the
    # Oracle couldn't answer.
    message: str
    source: Literal["form", "conversation"]
    conversation_id: uuid.UUID | None
    # Email Change Requests: the address the client asked for (Super Admin 5.1).
    requested_email: str | None
    internal_notes: str | None
    team_notified_at: datetime | None
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None


class SupportRequestPage(BaseModel):
    items: list[SupportRequestSummary]
    total: int
