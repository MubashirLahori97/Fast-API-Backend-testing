from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_message
from app.support.schemas import SupportRequestDetail, SupportRequestSummary


class SupportRequestList(BaseModel):
    items: list[SupportRequestSummary]
    total: int
    message: str | None = None  # "There are no support requests right now."


class AdminSupportRequestDetail(SupportRequestDetail):
    # Email Change Requests that are still open: 3.1's confirmation, filled in.
    change_email_confirmation: str | None = None


class SupportNotesBody(RequestBody):
    """The team's internal notes, replaced as a whole (empty clears them)."""

    notes: str | None = Field(default=None, max_length=settings.admin_note_max_length * 2)

    @field_validator("notes", mode="before")
    @classmethod
    def check_notes(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = clean_message(value)
        if len(value) > settings.admin_note_max_length:
            raise ValueError(
                f"Please keep the notes to {settings.admin_note_max_length:,} characters or fewer."
            )
        return value or None
