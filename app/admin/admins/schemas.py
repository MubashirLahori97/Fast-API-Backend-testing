"""Admin Management's bodies (Super Admin 7.1 and 7.2), with the stories' messages."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from app.auth.schemas import normalize_email
from app.core.config import settings
from app.core.schemas import RequestBody, clean_line, clean_name

AdminStatus = Literal["invite_pending", "invite_expired", "active", "deactivated"]
AdminAction = Literal["edit", "deactivate", "reactivate", "resend_invite", "cancel_invite"]

NAMES_EMPTY = "Please enter the admin’s first and last name."
REASON_EMPTY = "Please add a reason for deactivating this admin."


class AdminSummary(BaseModel):
    """One row of the listing (7.1). `id` is the Admin's id in Admin Management, the same from
    the invite to deactivation; `user_id` is their account, once set up."""

    id: uuid.UUID
    user_id: uuid.UUID | None
    first_name: str
    last_name: str
    email: str
    status: AdminStatus
    added_at: datetime
    last_active_at: datetime | None


class AdminPage(BaseModel):
    items: list[AdminSummary]
    total: int
    # "No admins match your search." when a search or filter finds nothing.
    message: str | None = None


class AdminPermissions(BaseModel):
    """7.2's Admin Permissions, shown on the details screen."""

    can: str
    cannot: list[str]


class AdminDetails(AdminSummary):
    added_by: str | None  # the inviter's name
    invite_expires_at: datetime | None  # while the invite is pending or expired
    deactivated_at: datetime | None
    deactivation_reason: str | None
    permissions: AdminPermissions
    actions: list[AdminAction]
    # 7.1's confirmation, for the Deactivate dialog; null when Deactivate isn't offered.
    deactivate_confirmation: str | None


class AdminResult(BaseModel):
    message: str
    admin: AdminDetails


def _name(value: str) -> str:
    value = clean_name(value)
    if not value:
        raise ValueError(NAMES_EMPTY)
    return value


class AdminNamesIn(RequestBody):
    first_name: str = ""
    last_name: str = ""

    @field_validator("first_name", "last_name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return _name(value)


class InviteAdminIn(AdminNamesIn):
    """7.2's Add Admin form."""

    email: str = ""

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value, "Email is required.")


class EditAdminIn(AdminNamesIn):
    """7.1's Edit: first and last name. The email can be sent unchanged (the panel may send
    the whole form), but can't be changed."""

    email: str | None = None


class DeactivateAdminIn(RequestBody):
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def check_reason(cls, value: str) -> str:
        value = clean_line(value)
        if not value:
            raise ValueError(REASON_EMPTY)
        if len(value) > settings.admin_reason_max_length:
            raise ValueError(
                f"Please keep this to {settings.admin_reason_max_length} characters or fewer."
            )
        return value
