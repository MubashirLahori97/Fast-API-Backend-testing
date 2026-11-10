"""Audit Logs' bodies (Super Admin 10.1).

The filters travel in a POST body, not the URL: a search can be a Client's name or email, and
URLs end up in server and proxy logs.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_line

AuditCategory = Literal[
    "sign_in_security",
    "client_accounts",
    "consent",
    "data",
    "escalations",
    "support_requests",
    "knowledge_base",
    "admins",
    "plans",
    "admin_views",
    "subscriptions",
    "other",
]
AuditRole = Literal["client", "teen", "admin", "super_admin", "system", "anonymous"]


class AuditFilters(RequestBody):
    """10.1's Search and Filter. Dates are times with a time zone (the panel sends the start and
    end of the admin's chosen days); a time without one is taken as UTC. Both ends included."""

    search: str | None = Field(default=None, max_length=200)  # a name or email
    role: AuditRole | None = None
    category: AuditCategory | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None

    @field_validator("search")
    @classmethod
    def check_search(cls, value: str | None) -> str | None:
        value = clean_line(value) if value is not None else None
        return value or None

    @field_validator("occurred_from", "occurred_to")
    @classmethod
    def check_time_zone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    @model_validator(mode="after")
    def check_range(self) -> "AuditFilters":
        if self.occurred_from and self.occurred_to and self.occurred_from > self.occurred_to:
            raise ValueError("Please choose an end date after the start date.")
        return self


class AuditSearch(AuditFilters):
    limit: int = Field(
        default=settings.audit_log_page_size, ge=1, le=settings.audit_log_max_page_size
    )
    offset: int = Field(default=0, ge=0)


class AuditActor(BaseModel):
    """Who: their name and role. Null id and name for the system or someone not signed in."""

    id: uuid.UUID | None
    name: str | None
    email: str | None
    role: AuditRole
    role_label: str


class AuditTarget(BaseModel):
    """What it affected: a type (user, admin_invitation, support_request...) and id, with a
    name for accounts and Admin invites."""

    type: str | None
    id: str | None
    name: str | None


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    action: str
    action_label: str
    category: AuditCategory
    category_label: str
    actor: AuditActor
    target: AuditTarget
    # Device and IP address, for sign-in and security events only (10.1).
    ip_address: str | None
    device: str | None
    # The reason given for a deactivation or reactivation (Super Admin 3.2 and 7.1).
    reason: str | None


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    has_more: bool
    # "No entries match your filters." when nothing matches.
    message: str | None = None


class AuditOption(BaseModel):
    code: str
    label: str


class AuditFilterOptions(BaseModel):
    categories: list[AuditOption]
    roles: list[AuditOption]
