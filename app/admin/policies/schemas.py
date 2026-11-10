"""Consent Management (Super Admin and Admin stories 9.1 and 9.2)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_message

PolicyKind = Literal["terms", "privacy", "health_consent"]


class PersonRef(BaseModel):
    id: uuid.UUID
    first_name: str | None


class PolicyRow(BaseModel):
    kind: PolicyKind
    name: str
    live_version: str | None
    published_at: datetime | None
    accepted: int  # Clients who've accepted the live version
    not_accepted: int  # and those who haven't yet
    has_draft: bool


class PolicyList(BaseModel):
    items: list[PolicyRow]


class VersionRef(BaseModel):
    """A published version in the history, which opens read-only."""

    id: uuid.UUID  # the policy_versions id
    version: str
    title: str
    published_at: datetime
    published_by: PersonRef | None


class VersionDetail(VersionRef):
    kind: PolicyKind
    text: str | None  # None for versions published before the admin panel kept texts
    summary_of_changes: str | None
    url: str | None
    read_only: bool = True


class DraftOut(BaseModel):
    version: str
    text: str
    summary_of_changes: str
    created_at: datetime
    updated_at: datetime
    updated_by: PersonRef | None


class PolicyDetail(BaseModel):
    kind: PolicyKind
    name: str
    live: VersionDetail | None
    history: list[VersionRef]  # earlier versions, newest first
    draft: DraftOut | None
    accepted: int
    not_accepted: int


class DraftBody(RequestBody):
    """Saving a draft: the fields sent replace what's there. Either may be empty until it's
    published."""

    text: str | None = Field(default=None, max_length=settings.policy_text_max_length)
    summary_of_changes: str | None = Field(
        default=None, max_length=settings.policy_summary_max_length
    )

    @field_validator("text", "summary_of_changes", mode="before")
    @classmethod
    def clean(cls, value: object) -> object:
        return clean_message(value) if isinstance(value, str) else value


class DraftSaved(BaseModel):
    draft: DraftOut
    message: str


class PreviewOut(BaseModel):
    """9.2's Preview: the version as clients will see it on the Policy Update screen."""

    kind: PolicyKind
    name: str
    version: str
    summary_of_changes: str
    text: str
    publish_confirmation: str


class PublishBody(RequestBody):
    confirmed: bool = False


class Published(BaseModel):
    policy: PolicyDetail
    message: str


class PublicPolicyOut(BaseModel):
    """A published version's text, for the apps' policy screens (no sign-in needed: the
    policies are public)."""

    id: uuid.UUID
    kind: PolicyKind
    version: str
    title: str
    text: str | None
    summary_of_changes: str | None
    url: str | None
    published_at: datetime
    status: Literal["published"] = "published"
