"""Knowledge Base Management (Super Admin and Admin stories 6.1 to 6.3, 6 Nov 19:22). Content
is Deborah's public material; a knowledge gap's question is a client's words, shown without who
asked. No Content Sources and no source field: all content comes from Add New Content."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_line, clean_message

ContentType = Literal[
    "book",
    "protocol",
    "blog_post",
    "qa_answer",
    "symptom_chart",
    "diagnostic_tree",
    "case_study",
    "knowledge_gap_answer",
]
ContentStatus = Literal["draft", "pending_approval", "published", "rejected", "archived"]
VersionStatus = Literal["draft", "pending_approval", "published", "rejected", "superseded"]
# The form's buttons: Save as draft for everyone; Publish for the Super Admin (Super Admin
# 6.2); Send for approval for Admins (Admin 6.2). Publishing is refused for Admins.
SaveAction = Literal["draft", "publish", "send_for_approval"]
GapStatus = Literal["new", "answer_pending", "answered", "dismissed"]

# Super Admin 6.1 to 6.3's messages.
TITLE_EMPTY = "Please add a title."
TYPE_EMPTY = "Please choose a content type."
NO_CONTENT = "Please upload a file, or add the text."
REJECT_REASON_EMPTY = "Please add a reason for rejecting this content."
DISMISS_REASON_EMPTY = "Please add a reason for dismissing this gap."


def _reason(value: object, empty_message: str) -> object:
    if value is None:
        value = ""
    if not isinstance(value, str):
        return value
    value = clean_message(value)
    if not value:
        raise ValueError(empty_message)
    if len(value) > settings.admin_reason_max_length:
        raise ValueError(
            f"Please keep the reason to {settings.admin_reason_max_length} characters or fewer."
        )
    return value


class _ContentFields(RequestBody):
    title: str = Field(default="", max_length=settings.knowledge_title_max_length * 2)
    content_type: ContentType | None = None
    # Typed or pasted text, or an uploaded file's id from POST /admin/knowledge/files (or both).
    text: str | None = Field(default=None, max_length=settings.knowledge_text_max_length)
    file_id: uuid.UUID | None = None
    action: SaveAction = "draft"

    @field_validator("title", mode="before")
    @classmethod
    def check_title(cls, value: object) -> object:
        if value is None:
            value = ""
        if not isinstance(value, str):
            return value
        value = clean_line(value)
        if not value:
            raise ValueError(TITLE_EMPTY)
        if len(value) > settings.knowledge_title_max_length:
            raise ValueError(
                f"Please keep the title to {settings.knowledge_title_max_length} characters or "
                "fewer."
            )
        return value

    @field_validator("content_type", mode="before")
    @classmethod
    def check_type(cls, value: object) -> object:
        if value in (None, ""):
            raise ValueError(TYPE_EMPTY)
        return value

    @field_validator("text", mode="before")
    @classmethod
    def check_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return clean_message(value) or None

    @field_validator("file_id")
    @classmethod
    def check_content(cls, value: uuid.UUID | None, info: ValidationInfo) -> uuid.UUID | None:
        if value is None and not info.data.get("text"):
            raise ValueError(NO_CONTENT)
        return value


class ContentNew(_ContentFields):
    """6.2's Add Content form. `knowledge_gap_id` is set when it's added from a gap's Add
    answer (6.3)."""

    knowledge_gap_id: uuid.UUID | None = None


class ContentEdit(_ContentFields):
    """6.1's Edit: the title, content type and text (or file)."""


class RejectBody(RequestBody):
    reason: str = Field(default="", max_length=settings.admin_reason_max_length * 2)

    @field_validator("reason", mode="before")
    @classmethod
    def check_reason(cls, value: object) -> object:
        return _reason(value, REJECT_REASON_EMPTY)


class DismissBody(RequestBody):
    reason: str = Field(default="", max_length=settings.admin_reason_max_length * 2)

    @field_validator("reason", mode="before")
    @classmethod
    def check_reason(cls, value: object) -> object:
        return _reason(value, DISMISS_REASON_EMPTY)


class RollbackBody(RequestBody):
    version: int = Field(ge=1)


class PersonRef(BaseModel):
    id: uuid.UUID
    first_name: str | None


class FileOut(BaseModel):
    id: uuid.UUID
    name: str
    media_type: str
    size_bytes: int
    uploaded_at: datetime


class ContentRow(BaseModel):
    id: uuid.UUID
    title: str
    content_type: ContentType
    status: ContentStatus
    version: int  # the latest version
    live_version: int | None  # what the Oracle uses (not while archived)
    updated_at: datetime


class ContentPage(BaseModel):
    items: list[ContentRow]
    total: int
    message: str | None = None  # "No content matches your search."


class VersionOut(BaseModel):
    number: int
    title: str
    content_type: ContentType
    status: VersionStatus
    rejection_reason: str | None
    rolled_back_from: int | None
    has_file: bool
    created_by: PersonRef | None
    created_at: datetime
    updated_at: datetime
    reviewed_by: PersonRef | None
    reviewed_at: datetime | None
    published_at: datetime | None
    rollback_confirmation: str  # "Publish version [X] instead of the current version?"


class VersionDetail(VersionOut):
    text: str | None
    file: FileOut | None


class GapRef(BaseModel):
    id: uuid.UUID
    question: str
    status: GapStatus


class ContentDetail(ContentRow):
    # The latest version, to read.
    text: str | None
    file: FileOut | None
    rejection_reason: str | None  # when the latest version was rejected: the Super Admin's
    knowledge_gap: GapRef | None
    versions: list[VersionOut]  # newest first
    # Approve & publish and Reject: only for the Super Admin, on a pending item (Admin 6.1:
    # pending items show their status with no Approve or Reject buttons).
    can_review: bool
    archive_confirmation: str


class ContentSaved(BaseModel):
    content: ContentDetail
    message: str


class KnowledgeScreen(BaseModel):
    """6.1's Knowledge Base screen: the number of new gaps (and content waiting for approval).
    The listing is GET /admin/knowledge/contents."""

    new_gaps: int
    pending_approval: int


class GapRow(BaseModel):
    id: uuid.UUID
    question: str
    topic: str | None
    times_asked: int
    status: GapStatus
    first_asked_at: datetime
    last_asked_at: datetime


class GapPage(BaseModel):
    items: list[GapRow]
    total: int
    topics: list[str]  # for the topic filter
    message: str | None = None  # "There are no knowledge gaps right now."


class AnswerContentRef(BaseModel):
    """The gap's answer: an Admin's waiting for approval, the published one, or an Admin's
    rejected one, with the Super Admin's reason (6.3: back to New, with the reason on the
    answer)."""

    id: uuid.UUID
    title: str
    status: ContentStatus
    rejection_reason: str | None = None


class AddAnswerPrefill(BaseModel):
    """6.3's Add answer: the Add Content form with the question filled in."""

    title: str
    content_type: ContentType = "knowledge_gap_answer"
    knowledge_gap_id: uuid.UUID


class GapDetail(GapRow):
    dismissed_reason: str | None
    dismissed_at: datetime | None
    dismissed_by: PersonRef | None
    answered_at: datetime | None
    answer_content: AnswerContentRef | None
    add_answer: AddAnswerPrefill


class GapActionOut(BaseModel):
    gap: GapDetail
    message: str
