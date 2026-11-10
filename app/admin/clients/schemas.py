"""Client Management (Super Admin and Admin stories 3.1 and 3.2). Only what's needed to
support the account, including the health profile, read-only (6 Nov 19:22): no conversations,
guidance summaries, provider notes or visit logs. Plan and subscription fields are None for
Admins, and the endpoints leave None fields out, so subscription details are never sent to an
Admin's screen."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.schemas import RequestBody, clean_message
from app.health.schemas import AboutYouOut, SectionOut

AccountType = Literal["adult", "teen"]
ClientPlan = Literal["trial", "individual", "family"]
ClientStatus = Literal[
    "trial",
    "active",
    "payment_issue",
    "cancelled",
    "consent_revoked",
    "deactivated",
    # 3.1 (6 Nov 19:22): during the 10-day grace period, and after it until the deletion is
    # complete.
    "scheduled_for_deletion",
    "being_deleted",
]

REASON_EMPTY = "Please add a reason for deactivating this account."


class ClientRow(BaseModel):
    id: uuid.UUID
    first_name: str
    email: str
    state: str | None
    account_type: AccountType
    plan: ClientPlan | None = None  # Super Admin only; teens have no plan
    status: ClientStatus
    family_members: int | None = None  # adults only
    signed_up_at: datetime
    last_active_at: datetime | None = None


class ClientPage(BaseModel):
    items: list[ClientRow]
    total: int
    message: str | None = None  # "No clients match your search."


class AccountOut(BaseModel):
    first_name: str
    email: str
    state: str | None
    state_name: str | None
    zip_code: str | None  # Super Admin and Admin 3.1 (6 Nov); null on accounts without one
    account_type: AccountType
    signed_up_at: datetime
    status: ClientStatus


class SubscriptionOut(BaseModel):
    """Super Admin only."""

    plan: ClientPlan
    status: Literal["trial", "active", "payment_issue", "cancelled", "ended"]
    trial_ends_at: datetime | None = None
    next_billing_date: datetime | None = None
    add_on_members: int = 0


class AcceptedPolicyOut(BaseModel):
    kind: Literal["terms", "privacy", "health_consent"]
    title: str
    version: str
    accepted_at: datetime


class ConsentOut(BaseModel):
    revoked: bool
    label: str | None = None  # "Consent revoked"
    accepted: list[AcceptedPolicyOut]


class FamilyMemberOut(BaseModel):
    """A managed family member: first name, relationship and age only."""

    id: uuid.UUID
    first_name: str | None
    relationship: str | None
    age: int | None = None
    turned_off: bool
    deletion_requested: bool


class InvitedTeenOut(BaseModel):
    account_id: uuid.UUID | None = None
    first_name: str
    status: Literal["invite_sent", "joined", "turned_off", "access_paused"]


class TeenLinkOut(BaseModel):
    parent_account_id: uuid.UUID
    parent_first_name: str
    access: Literal["active", "paused"]


class OpenSupportRequest(BaseModel):
    id: uuid.UUID
    kind: str


class OpenDeletionRequest(BaseModel):
    id: uuid.UUID
    kind: str
    status: str


class OpenEscalation(BaseModel):
    id: uuid.UUID
    level: str


class ActivityOut(BaseModel):
    last_active_at: datetime | None = None
    conversations: int
    open_support_requests: list[OpenSupportRequest]
    open_deletion_requests: list[OpenDeletionRequest]
    escalations_not_reviewed: list[OpenEscalation]


class ConfirmationsOut(BaseModel):
    """The stories' confirmation texts, filled in for this client."""

    deactivate: str
    teens_affected: str | None = None  # only when the parent has invited teens
    reactivate: str


class HealthProfileView(BaseModel):
    """3.1's health profile, read-only: the client's own profile (a teen's too), as My Health
    shows it, without what's only for editing (no editable fields, suggested answers, or the
    conversation an answer came from). Health data."""

    profile_id: uuid.UUID
    completion: int
    complete: bool
    about_you: AboutYouOut
    sections: list[SectionOut]
    question_bank_version: str


class ClientDetail(BaseModel):
    id: uuid.UUID
    account: AccountOut
    subscription: SubscriptionOut | None = None  # Super Admin only
    consent: ConsentOut
    family_members: list[FamilyMemberOut]
    invited_teens: list[InvitedTeenOut]
    teen_account: TeenLinkOut | None = None  # teens only
    activity: ActivityOut
    # Super Admin and Admin 3.1: null (left out) when the client has no health profile yet.
    health_profile: HealthProfileView | None = None
    # The open Email Change Request, for Change email address (POST
    # /admin/support-requests/{id}/change-email).
    email_change_request_id: uuid.UUID | None = None
    can_deactivate: bool
    can_reactivate: bool
    confirmations: ConfirmationsOut


class DeactivateBody(RequestBody):
    reason: str = Field(default="", max_length=settings.admin_reason_max_length * 2)

    @field_validator("reason", mode="before")
    @classmethod
    def check_reason(cls, value: object) -> object:
        if value is None:
            value = ""
        if not isinstance(value, str):
            return value
        value = clean_message(value)
        if not value:
            raise ValueError(REASON_EMPTY)
        if len(value) > settings.admin_reason_max_length:
            raise ValueError(
                f"Please keep the reason to {settings.admin_reason_max_length} characters or fewer."
            )
        return value


class ClientActionOut(BaseModel):
    status: ClientStatus
    message: str
