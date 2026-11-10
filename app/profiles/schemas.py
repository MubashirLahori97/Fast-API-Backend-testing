"""Health intake for the client (story 2.1) and for a family member (story 2.2), and managing
family members (story 8.2).

Options are stored as snake_case codes; the apps show the labels. The codes and labels live in
options.py, which GET /profiles/options serves.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ValidationError, ValidationInfo, field_validator

from app.core.schemas import RequestBody, clean_name
from app.profiles import options
from app.profiles.options import (
    AdvocateConsent,
    FamilyRelationship,
    GenderIdentity,
    Pronouns,
    SexAtBirth,
    TeenProfileChoice,
)
from app.teens.schemas import InvitedTeenOut

IntakeQuestion = Literal[
    "family_relationship",
    "first_name",
    "date_of_birth",
    "teen_profile_choice",
    "advocate_consent",
    "sex_at_birth",
    "gender_identity",
    "pronouns",
]
# The questions after "Who is this profile for?", in the order the app asks them. The client's
# own date of birth isn't asked: it comes from sign-up (story 2.1).
SELF_QUESTIONS: tuple[IntakeQuestion, ...] = (
    "sex_at_birth",
    "gender_identity",
    "pronouns",
)
# teen_profile_choice is only asked for a member aged 13 to 17 (story 2.2).
FAMILY_QUESTIONS: tuple[IntakeQuestion, ...] = (
    "family_relationship",
    "first_name",
    "date_of_birth",
    "teen_profile_choice",
    "advocate_consent",
    "sex_at_birth",
    "gender_identity",
    "pronouns",
)
FAMILY_ONLY_FIELDS = (
    "family_relationship",
    "first_name",
    "teen_profile_choice",
    "advocate_consent",
)
# Story 8.2: "active", "turned_off", "scheduled_for_deletion" (removed, in the 10-day grace
# period: fully usable, the card shows "Scheduled for deletion on [date]"), or
# "deletion_requested" (the grace period has ended: locked until the team deletes it).
MemberStatus = Literal["active", "turned_off", "scheduled_for_deletion", "deletion_requested"]

# Stories 2.1 and 2.2: a question left unanswered, or answered with a code the backend
# doesn't know (for example from an app that has older options).
CHOOSE_AN_OPTION = "Please choose an option to continue."
# Story 1.1's wording, for a date that isn't a date at all. The service names the family
# member for a date in the future (story 2.2), but the name isn't known here.
INVALID_DATE_OF_BIRTH = "Please enter a valid date of birth."
CHOICE_FIELDS = (
    "family_relationship",
    "teen_profile_choice",
    "advocate_consent",
    "sex_at_birth",
    "gender_identity",
    "pronouns",
)


def _first_name(value: str | None, empty_message: str) -> str | None:
    """Trimmed, with a capital first letter: "azka" is shown as "Azka" (story 2.2)."""
    if value is None:
        return None
    value = clean_name(value)
    if not value:
        raise ValueError(empty_message)
    return value[0].upper() + value[1:]


def _known_choice(value: object, handler):
    """Gives an unknown code the stories' "Please choose an option to continue." instead of
    Pydantic's list of allowed values."""
    try:
        return handler(value)
    except ValidationError:
        raise ValueError(CHOOSE_AN_OPTION) from None


class IntakeAnswers(RequestBody):
    """The answer to one intake step. Send only that step's fields. The Back button changes
    an earlier answer by sending it again. Family-only fields are refused on the client's own
    profile, and so is a date of birth different from sign-up's."""

    family_relationship: FamilyRelationship | None = None
    first_name: str | None = None
    date_of_birth: date | None = None
    # Story 2.2, for a member aged 13 to 17 only. "own_account" needs the Family plan (1.5), and
    # then the invite (next_question "teen_invite") instead of steps 4 to 7.
    teen_profile_choice: TeenProfileChoice | None = None
    advocate_consent: AdvocateConsent | None = None
    sex_at_birth: SexAtBirth | None = None
    gender_identity: GenderIdentity | None = None
    gender_identity_other: str | None = None  # with "not_listed"
    pronouns: Pronouns | None = None
    pronouns_other: str | None = None  # with "other"

    @field_validator(*CHOICE_FIELDS, mode="wrap")
    @classmethod
    def check_choice(cls, value: object, handler):
        return _known_choice(value, handler)

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str | None) -> str | None:
        return _first_name(value, "What should I call them? Please enter their first name.")

    @field_validator("date_of_birth", mode="wrap")
    @classmethod
    def check_date_of_birth(cls, value: object, handler) -> date | None:
        # A date in the future, or too far back, is refused by the service, which knows the
        # member's name for the message.
        try:
            return handler(value)
        except ValidationError:
            raise ValueError(INVALID_DATE_OF_BIRTH) from None

    @field_validator("gender_identity_other")
    @classmethod
    def check_gender_other(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _write_in(value, info.data.get("gender_identity"), options.GENDER_IDENTITY)

    @field_validator("pronouns_other")
    @classmethod
    def check_pronouns_other(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _write_in(value, info.data.get("pronouns"), options.PRONOUNS)


def _write_in(value: str | None, choice: str | None, question: options.Question) -> str | None:
    """A write-in only counts with its choice ("Not listed" for gender, "Other" for pronouns);
    any other choice drops it. The service checks that the choice has one, because the message
    names the person."""
    if choice != question.write_in_choice:
        return None
    return clean_name(value or "") or None


class ProfileEdit(RequestBody):
    """View & edit a family member (story 8.2). Send the fields to change; the app may also send
    the whole form.

    - A write-in can be sent on its own while the saved choice takes one.
    - Changing the relationship needs the advocate consent again, in the same request (story
      2.2's step 4), so the consent always matches who the member is to the client.
    - Date of birth and sex at birth are read-only: accepted unchanged, refused if different.
    """

    first_name: str | None = None
    family_relationship: FamilyRelationship | None = None
    advocate_consent: AdvocateConsent | None = None
    gender_identity: GenderIdentity | None = None
    gender_identity_other: str | None = None
    pronouns: Pronouns | None = None
    pronouns_other: str | None = None
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None

    @field_validator(
        "family_relationship",
        "advocate_consent",
        "gender_identity",
        "pronouns",
        "sex_at_birth",
        mode="wrap",
    )
    @classmethod
    def check_choice(cls, value: object, handler):
        return _known_choice(value, handler)

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str | None) -> str | None:
        return _first_name(value, "Please enter their first name.")

    @field_validator("gender_identity_other", "pronouns_other")
    @classmethod
    def strip_write_in(cls, value: str | None) -> str | None:
        # The service pairs it with the sent or saved choice, which may not be in this request.
        return clean_name(value or "") or None


class DeletionRequestBody(RequestBody):
    """Story 8.2: the client types the family member's first name to confirm."""

    confirm_name: str | None = None


class IntakeOut(BaseModel):
    profile_id: uuid.UUID
    is_self: bool
    family_relationship: FamilyRelationship | None
    first_name: str | None  # family members only
    # The client's own comes from sign-up and can't be changed here.
    date_of_birth: date | None
    # True for a family member under 13: the gender step shows each choice's label_under_13
    # (Girl, Boy) from GET /profiles/options (story 2.2).
    under_13: bool
    teen_profile_choice: TeenProfileChoice | None
    advocate_consent: AdvocateConsent | None
    sex_at_birth: SexAtBirth | None
    gender_identity: GenderIdentity | None
    gender_identity_other: str | None
    pronouns: Pronouns | None
    pronouns_other: str | None
    # The question to show next (the resume point after sign-in), or "done". "teen_invite": the
    # Teen account privacy disclaimer and the teen's email (POST /profiles/{id}/teen-invite).
    next_question: IntakeQuestion | Literal["teen_invite", "done"]
    completed: bool


class IntakeCompleted(BaseModel):
    profile_id: uuid.UUID  # the app makes this the active profile (story 2.2)
    message: str  # the Oracle's welcome line


class ProfileOut(BaseModel):
    id: uuid.UUID
    is_self: bool
    first_name: str
    relationship: FamilyRelationship | None
    age: int | None
    intake_completed: bool
    # "active", or "deletion_requested": the grace period after Remove has ended, so it's still
    # listed while the team reviews it but can't be used (story 8.2). During the grace period
    # it's "active". Turned-off members aren't listed.
    status: MemberStatus


class ProfileDetails(BaseModel):
    """A profile's details for View & edit (story 8.2)."""

    id: uuid.UUID
    is_self: bool
    first_name: str
    family_relationship: FamilyRelationship | None
    date_of_birth: date | None  # read-only after the intake
    age: int | None
    under_13: bool  # the gender choices use label_under_13, as in the intake
    sex_at_birth: SexAtBirth | None  # read-only after the intake
    gender_identity: GenderIdentity | None
    gender_identity_other: str | None
    pronouns: Pronouns | None
    pronouns_other: str | None
    status: MemberStatus
    intake_completed: bool


class ProfileUpdated(BaseModel):
    profile: ProfileDetails
    message: str


class FamilyMemberOut(BaseModel):
    """A card on the Manage Family screen (story 8.2)."""

    id: uuid.UUID
    first_name: str
    relationship: FamilyRelationship
    age: int
    status: MemberStatus
    # "60% complete": the health profile's completion (story 6.1, app/health/service.py).
    health_profile_completion: int | None
    # Removed, in the grace period: the date for "Scheduled for deletion on [date]" (8.2).
    deletion_scheduled_on: datetime | None = None
    # The card's text, with the date filled in: "Scheduled for deletion on [date]".
    deletion_label: str | None = None


class FamilyOverview(BaseModel):
    """The Manage Family screen: "2 of 3 active family members" and a card for each member,
    turned-off ones included. Unfinished drafts aren't listed; Add family member resumes one.
    Invited teens have their own cards, with no health information (8.2), and count towards the
    places from the invite (8.1)."""

    family_members_used: int
    family_members_included: int
    members: list[FamilyMemberOut]
    invited_teens: list[InvitedTeenOut] = []


class FamilyMemberResult(BaseModel):
    member: FamilyMemberOut
    message: str
    # Where the app goes if this member was the active profile and can't stay active: the
    # client's own profile, or the first active family member for advocate-only clients.
    default_profile_id: uuid.UUID | None


# GET /profiles/options


class ChoiceOut(BaseModel):
    code: str  # what the app sends
    label: str  # may contain "[Name]", for the app to fill in
    # Gender only: the label for a family member under 13 (IntakeOut.under_13), when it differs.
    label_under_13: str | None
    description: str | None  # a line under the label, when there is one
    # False while the choice can't be picked yet. Every choice can be picked now.
    available: bool


class QuestionOptionsOut(BaseModel):
    choices: list[ChoiceOut]  # in the order the app shows them
    # The choice that needs a typed answer, and the field the answer is sent in; null if none.
    write_in_choice: str | None
    write_in_field: str | None


class PronounOptionsOut(QuestionOptionsOut):
    # The pronouns selected when the screen opens, by the gender chosen just before: They/Them
    # for Agender and Not listed. Genders not listed here have nothing selected.
    default_for_gender: dict[str, str]


class ProfileOptions(BaseModel):
    """The answer options for each intake question, and for View & edit (stories 2.1, 2.2,
    8.2). The keys are the field names sent to PATCH /profiles/{id}/intake."""

    family_relationship: QuestionOptionsOut
    teen_profile_choice: QuestionOptionsOut
    advocate_consent: QuestionOptionsOut
    sex_at_birth: QuestionOptionsOut
    gender_identity: QuestionOptionsOut
    pronouns: PronounOptionsOut
