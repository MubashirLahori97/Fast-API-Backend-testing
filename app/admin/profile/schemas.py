"""My Profile's bodies (Super Admin 12.1), with the story's messages."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from app.core.schemas import RequestBody, clean_name

NAMES_EMPTY = "Please enter your first and last name."


class AdminProfileOut(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    role: Literal["admin", "super_admin"]
    # This sign-in, and the one before it (null for a first sign-in).
    signed_in_at: datetime
    previous_sign_in_at: datetime | None
    # Always on for the admin panel (Super Admin 1.1): shown as On, and can't be turned off.
    two_step_verification: Literal["on"] = "on"


class AdminProfileEdit(RequestBody):
    """Edit and Save: the first and last name. The email can be sent unchanged (the panel may
    send the whole form), but can't be changed here."""

    first_name: str = ""
    last_name: str = ""
    email: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def check_name(cls, value: str) -> str:
        value = clean_name(value)
        if not value:
            raise ValueError(NAMES_EMPTY)
        return value


class AdminProfileUpdated(BaseModel):
    message: str
    profile: AdminProfileOut
