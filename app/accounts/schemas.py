import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.auth.schemas import INVALID_STATE, US_STATES, normalize_email, normalize_zip_code
from app.core.schemas import RequestBody, clean_name


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    version: str
    title: str
    url: str | None
    published_at: datetime


class MeOut(BaseModel):
    """What the app needs before the policy gate (/me answers before updated policies are
    accepted). The date of birth and state are personal data, so they're left out here;
    GET /me/profile (story 11.1) shows them behind the gate."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    # Every account is a client for now; the admin roles come with Phase A (docs/PLAN.md).
    role: Literal["client", "admin", "super_admin"]
    # "teen": an invited teen with their own account (story 1.5). The app shows the teen
    # version of the screens: no billing, no family members, their own chat after sign-in.
    account_type: Literal["adult", "teen"]
    first_name: str
    last_name: str | None
    # A teen has no trial: their access follows the parent's Family plan.
    trial_ends_at: datetime


class DeletionNoticeOut(BaseModel):
    """What the app shows during a grace period (stories 1.2, 8.2 and 11.4)."""

    deletion_on: datetime  # the end of the grace period
    # "Your account is scheduled for deletion on [date]." on every screen.
    banner: str
    # For an invited teen whose parent asked to delete their account, or who was removed by
    # the parent: 11.4's or 8.2's message with the date. Null for the account's own request.
    message: str | None


class NextStepOut(BaseModel):
    # account_being_deleted: the account's deletion grace period has ended (1.2, 11.4): the app
    # shows "Your account is being deleted, so it’s no longer available." and nothing else
    # works. During the grace period the usual step comes, with `deletion_notice`.
    # adult_sign_up: a teen account that has reached the age of majority (1.6): the Create My
    # Account message (GET /me/adult-account); Privacy & Data still works.
    # access_paused: an invited teen who has lost access (1.5): only Privacy & Data, with "Your
    # access is paused. Please ask your parent or guardian...".
    next_step: Literal[
        "account_being_deleted",
        "adult_sign_up",
        "access_paused",
        "policy_update",
        "intake",
        "upgrade",
        "dashboard",
    ]
    # For "intake": the profile to resume, or null when the client hasn't picked who the
    # first profile is for yet (step 1). For "dashboard": the profile to make active, which is
    # the client's own, or the first active family member for advocate-only clients (4.2).
    profile_id: uuid.UUID | None = None
    # During a deletion's grace period (1.2, 8.2, 11.4): the date, the banner "Your account is
    # scheduled for deletion on [date]." for every screen, and for an invited teen whose parent
    # asked to delete their account or removed them, the story's message. Null otherwise.
    deletion_notice: DeletionNoticeOut | None = None


class EntitlementsOut(BaseModel):
    plan: Literal["trial", "individual", "family"]  # app.billing.entitlements.Plan
    trial_ends_at: datetime
    # The trial is over with no subscription: the message box is locked (story 3.1).
    trial_ended: bool
    # 0 on the trial and the Individual plan: family members are part of the Family plan (8.1)
    family_members_included: int
    family_members_used: int


class PolicyAcceptanceRequest(RequestBody):
    policy_version_ids: list[uuid.UUID] = []


# Story 11.1: Profile & Account

FIRST_NAME_EMPTY = "Please enter your first name."
STATE_EMPTY = "Please choose your state."
INVALID_ZIP_CODE = "Please enter a valid ZIP code."
# Not in the stories (docs/decisions/phase-10-account.md).
COUNTRY_LOCKED = "Your Oracle is for U.S. users only, so the country can’t be changed."
INVALID_EMAIL = "Please enter a valid email address."


class MyProfileOut(BaseModel):
    """The Profile & Account screen's account details: no phone number, and the ZIP code is
    back in the 6 Nov stories."""

    first_name: str
    initial: str  # the first letter of the first name, for the avatar
    email: str
    date_of_birth: date | None  # null only on accounts made before sign-up asked for it
    country: str | None  # always "US"; can't be changed
    state: str | None  # the USPS code, e.g. "CA"
    state_name: str | None  # e.g. "California"
    # Null on accounts made without one (before 6 Nov, teens' own accounts, transferred
    # profiles); the client can add it with Edit.
    zip_code: str | None
    # Which age rules the Oracle follows for the client: the state's age of majority against
    # their date of birth. "teen" means education only (story 3.1).
    age_rules: Literal["adult", "teen"]
    # Story 11.1: shown as "Email change requested" until the support team changes it.
    email_change_requested: bool
    requested_email: str | None
    # Story 11.1: a client with no health profile of their own (they deleted their own data,
    # 11.4, or only ever added family members, 2.2) sees their details and settings only.
    advocate_only: bool


class MyProfileEdit(RequestBody):
    """Edit: the first name, the state and the ZIP code can change. The other fields on the
    screen may be sent back unchanged, so the app can send the whole form; a different email,
    date of birth or country is refused. `confirm_teen_rules` is the client's Confirm on the
    teen rules message, sent again with the same state."""

    first_name: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None
    email: str | None = None
    date_of_birth: date | None = None
    confirm_teen_rules: bool = False

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = clean_name(value)
        if not value:
            raise ValueError(FIRST_NAME_EMPTY)
        return value

    @field_validator("state")
    @classmethod
    def check_state(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError(STATE_EMPTY)
        if value not in US_STATES:
            raise ValueError(INVALID_STATE)
        return value

    @field_validator("zip_code")
    @classmethod
    def check_zip_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        zip_code = normalize_zip_code(value)
        if zip_code is None:
            raise ValueError(INVALID_ZIP_CODE)
        return zip_code

    @field_validator("country")
    @classmethod
    def check_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip().upper() != "US":
            raise ValueError(COUNTRY_LOCKED)
        return "US"

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return None if value is None else value.strip().lower()


class MyProfileUpdated(BaseModel):
    profile: MyProfileOut
    message: str


class EmailChangeRequestBody(RequestBody):
    """Story 11.1's Request email change. The app makes `client_request_id` once per request
    and sends it again with any retry, so the request reaches the team once."""

    client_request_id: uuid.UUID
    new_email: str = ""

    @field_validator("new_email")
    @classmethod
    def check_new_email(cls, value: str) -> str:
        return normalize_email(value, INVALID_EMAIL)


class EmailChangeRequested(BaseModel):
    profile: MyProfileOut
    message: str
