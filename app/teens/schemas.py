"""Request and response bodies for teens with their own account (stories 1.5, 1.6, 2.4 and the
teen parts of 8.2 and 12.2). Messages are the stories' exact wording, or are listed in
docs/decisions/phase-3b-teens.md."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.accounts.schemas import PolicyOut
from app.auth.schemas import (
    INVALID_DATE_OF_BIRTH,
    INVALID_STATE,
    PASSWORD_RULES,
    PASSWORDS_DONT_MATCH,
    US_STATES,
    Platform,
    SignedIn,
    normalize_email,
)
from app.auth.security import meets_password_rules
from app.core.ages import today, years_before
from app.core.schemas import RequestBody, clean_name
from app.profiles.options import FamilyRelationship

# Story 1.5's messages.
DISCLAIMER_NOT_ACCEPTED = "Please confirm you understand your teen’s account privacy to continue."
TEEN_EMAIL_INVALID = "Please enter a valid email address for your teen."
FIELD_EMPTY = "Please complete this field."
# Story 1.1's, for the fields 1.5 has no message for.
FIRST_NAME_EMPTY = "Please enter your first name."
ACCEPT_TERMS = "Please accept the Terms of Service and Privacy Policy to continue."
# Not in the stories.
US_ONLY = "Your Oracle is for U.S. users only."
OLDEST_AGE = 120  # as at sign-up: a date of birth further back is a typo


def _state(value: str) -> str:
    value = value.strip().upper()
    if not value:
        raise ValueError(FIELD_EMPTY)
    if value not in US_STATES:
        raise ValueError(INVALID_STATE)
    return value


def _first_name(value: str) -> str:
    value = clean_name(value)
    if not value:
        raise ValueError(FIRST_NAME_EMPTY)
    return value


# The parent's side


class TeenInviteBody(RequestBody):
    """Story 1.5: the parent accepted the Teen account privacy disclaimer ("I understand &
    continue") and typed the teen's email. Sent for the family draft whose Teen Profile Choice is
    "own_account" (story 2.2)."""

    disclaimer_accepted: bool = False
    email: str = ""

    @field_validator("disclaimer_accepted")
    @classmethod
    def check_disclaimer(cls, value: bool) -> bool:
        if not value:
            raise ValueError(DISCLAIMER_NOT_ACCEPTED)
        return value

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        try:
            return normalize_email(value, TEEN_EMAIL_INVALID)
        except ValueError:
            raise ValueError(TEEN_EMAIL_INVALID) from None


class TeenHealthConsentBody(RequestBody):
    """Story 12.2: the parent confirms the updated Health Consent, as medical advocate, for an
    invited teen."""

    policy_version_id: uuid.UUID | None = None


TeenLinkStatus = Literal["invite_sent", "joined", "turned_off", "access_paused"]


class InvitedTeenOut(BaseModel):
    """An invited teen's card on Manage Family (story 8.2): their first name and relationship
    as the parent entered them, and the status. Never the teen's health, profile or activity."""

    id: uuid.UUID  # the link's id, for the /teen-links/{link_id} actions
    first_name: str
    relationship: FamilyRelationship
    # invite_sent, joined, turned_off or access_paused (the parent's Family plan isn't active,
    # or an updated Health Consent waits for them)
    status: TeenLinkStatus
    active: bool  # the Active toggle: false once turned off
    can_resend: bool  # Resend invite, while the invite is pending
    # Story 12.2: confirm the updated Health Consent for this teen (POST .../health-consent).
    health_consent_needed: bool
    # Story 8.2's confirmations, with the name filled in, for the app to show first.
    turn_off_confirmation: str
    remove_confirmation: str


class TeenInviteSent(BaseModel):
    invited_teen: InvitedTeenOut
    message: str  # "Invitation sent. We’ve emailed [teen email] with instructions..."


class TeenLinkResult(BaseModel):
    invited_teen: InvitedTeenOut
    message: str


# The teen's side


class TeenInviteToken(RequestBody):
    """The token from the invite link's `#token=...`. Sent in the body, never in a URL."""

    token: str = Field(min_length=1, max_length=200)


class TeenInviteOut(BaseModel):
    """What the teen setup screen shows (story 1.5): the email, filled in and locked, and the
    first name the parent typed, to start the name field with."""

    email: str
    first_name: str
    # The email already has an account: the app opens Sign In instead (1.5's "Teen already has
    # an account"). After signing in, a teen account sends the token to /teen-invites/link.
    account_exists: bool


class TeenSignUpBody(RequestBody):
    """Story 1.5's Teen Account Setup: About You, then Create Password with the email locked.
    No code, no consent and no subscription step: the parent gave consent and pays."""

    token: str = Field(min_length=1, max_length=200)
    first_name: str = ""  # "Preferred name or first name"
    date_of_birth: date | None = None
    city: str = ""
    state: str = ""
    country: str = ""
    password: str = ""
    confirm_password: str = ""
    platform: Platform = "web"  # as in sign-in: web sessions time out sooner (story 1.2)

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str) -> str:
        return _first_name(value)

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def check_date_of_birth(cls, value: object) -> date:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(FIELD_EMPTY)
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value.strip())
            except ValueError:
                raise ValueError(INVALID_DATE_OF_BIRTH) from None
        if not isinstance(value, date):
            raise ValueError(INVALID_DATE_OF_BIRTH)
        if value > today() or value < years_before(today(), OLDEST_AGE):
            raise ValueError(INVALID_DATE_OF_BIRTH)
        return value

    @field_validator("city")
    @classmethod
    def check_city(cls, value: str) -> str:
        value = clean_name(value)
        if not value:
            raise ValueError(FIELD_EMPTY)
        return value

    @field_validator("state")
    @classmethod
    def check_state(cls, value: str) -> str:
        return _state(value)

    @field_validator("country")
    @classmethod
    def check_country(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError(FIELD_EMPTY)
        if value != "US":
            raise ValueError(US_ONLY)
        return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not meets_password_rules(value):
            raise ValueError(PASSWORD_RULES)
        return value

    @field_validator("confirm_password")
    @classmethod
    def check_confirm_password(cls, value: str, info: ValidationInfo) -> str:
        if not value or ("password" in info.data and value != info.data["password"]):
            raise ValueError(PASSWORDS_DONT_MATCH)
        return value


class TeenSignedUp(SignedIn):
    """The teen's account is ready and this device is signed in. Next comes the teen onboarding
    (story 2.3) on `profile_id`, with PATCH /profiles/{id}/intake, after the welcome."""

    profile_id: uuid.UUID
    welcome_title: str
    welcome: str


# Story 1.6 and 2.4: the move to an adult account


class AdultAccountOut(BaseModel):
    """Create My Account (story 1.6): the adult sign-up, with the first name, date of birth and
    email filled in from the teen account. The email and date of birth can't change."""

    message: str  # 1.6's "You’ve reached adult age, so this account is no longer available..."
    first_name: str
    date_of_birth: date
    email: str
    country: str
    state: str | None
    policies: list[PolicyOut]  # the Terms of Service and Privacy Policy to accept


class AdultAccountBody(RequestBody):
    """The adult sign-up's details that can still change, and story 1.1's Terms of Service and
    Privacy Policy checkbox. The password stays: the teen is signed in with it."""

    first_name: str = ""
    state: str = ""
    accept_terms: bool = False

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str) -> str:
        return _first_name(value)

    @field_validator("state")
    @classmethod
    def check_state(cls, value: str) -> str:
        return _state(value)

    @field_validator("accept_terms")
    @classmethod
    def check_accept_terms(cls, value: bool) -> bool:
        if not value:
            raise ValueError(ACCEPT_TERMS)
        return value


class AdultAccountCreated(BaseModel):
    message: str  # 1.6's "Your history has been moved to your new account."
    trial_message: str  # 2.4's "Your 14-day free trial has started..."
    trial_ends_at: datetime
    # 2.4: straight to the Home Dashboard, with this profile active. No onboarding again.
    next_step: Literal["dashboard", "intake"]
    profile_id: uuid.UUID | None
