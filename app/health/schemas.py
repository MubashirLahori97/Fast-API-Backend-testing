"""My Health (story 6.1), its Hypothalamus Circle Map, and the changes a logged visit suggests
(5.2), which the client confirms first."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator

from app.core.schemas import RequestBody, clean_name
from app.health.bank import Column, Kind, WhenAsked
from app.profiles.options import GenderIdentity, Pronouns, SexAtBirth
from app.profiles.schemas import CHOOSE_AN_OPTION, INVALID_DATE_OF_BIRTH

AnswerSource = Literal["client", "conversation"]
FactStatus = Literal["pending", "confirmed", "discarded"]


class AnswerIn(RequestBody):
    """One answer, in the form its question's kind takes (app/health/values.py). `other` is the
    write-in, for the choice that takes one."""

    value: Any = None
    other: str | None = None


class AboutYouEdit(RequestBody):
    """Story 6.1's About you: only gender identity and pronouns can change, and the Oracle uses
    the new wording straight away. Date of birth and sex at birth decide which questions apply,
    so they're read-only: accepted unchanged, refused if different."""

    gender_identity: GenderIdentity | None = None
    gender_identity_other: str | None = None  # with "not_listed"
    pronouns: Pronouns | None = None
    pronouns_other: str | None = None  # with "other"
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None

    @field_validator("gender_identity", "pronouns", "sex_at_birth", mode="wrap")
    @classmethod
    def check_choice(cls, value: object, handler):
        try:
            return handler(value)
        except ValidationError:
            raise ValueError(CHOOSE_AN_OPTION) from None

    @field_validator("date_of_birth", mode="wrap")
    @classmethod
    def check_date_of_birth(cls, value: object, handler):
        try:
            return handler(value)
        except ValidationError:
            raise ValueError(INVALID_DATE_OF_BIRTH) from None

    @field_validator("gender_identity_other", "pronouns_other")
    @classmethod
    def strip_write_in(cls, value: str | None) -> str | None:
        # The service pairs it with the sent or saved choice.
        return clean_name(value or "") or None


class HealthProfileEdit(RequestBody):
    """A save in My Health: one section's Edit, or a step of Complete my profile.

    - `answers`: question key -> the new answer, or null to remove it (6.1: optional and
      sensitive answers "can be edited or deleted at any time"). An empty text also removes.
      Answers that depend on each other can be sent together: each question is checked with
      the answers before it in this same save.
    - `remove_sections`: removes every saved answer in these sections, including answers kept
      from questions that no longer apply (for example "body_follow_ups").
    - Nothing is saved if any part is refused.
    """

    about_you: AboutYouEdit | None = None
    answers: dict[str, AnswerIn | None] = {}
    remove_sections: list[str] = []


class ChoiceOut(BaseModel):
    code: str
    label: str


class AnswerOut(BaseModel):
    value: Any
    other: str | None
    # "conversation": saved by the Oracle from a conversation (3.1), and the app shows "Added
    # from our conversation on [date]" (6.1) with added_from_conversation_at. conversation_id is
    # null once that conversation is gone. Changing it in My Health makes it "client".
    source: AnswerSource
    conversation_id: uuid.UUID | None
    updated_at: datetime
    added_from_conversation_at: datetime | None  # set exactly when source is "conversation"


class QuestionOut(BaseModel):
    key: str
    kind: Kind
    title: str  # with the family member's name and pronouns filled in
    hint: str | None
    # The routing document's "When asked": asked_first (the first time it's relevant),
    # asked_later (only when it helps the concern), conversation (the follow-up body questions)
    # or onboarding. Every question can be answered here in My Health too.
    when_asked: WhenAsked
    # choice, multi_choice, checklist and history: only the choices shown to this profile.
    choices: list[ChoiceOut]
    exclusive: list[str]  # multi_choice codes that can't go with others ("None of these")
    write_in_choice: str | None  # the code that takes a typed answer in `other`
    write_in_label: str | None
    write_in_required: bool
    min: float | None  # number and scale
    max: float | None
    integer: bool
    unit: str | None
    min_label: str | None  # scale
    max_label: str | None
    name_label: str | None  # named_list: each item has a name and a detail
    detail_label: str | None
    # history: the columns offered, "self" and "family" (teens and children: family only).
    columns: list[Column]
    optional: bool
    # Sensitive answers are never sent to analytics, ad pixels or Shopify (6.1).
    sensitive: bool
    counted: bool  # counts toward the completion percentage
    answer: AnswerOut | None  # null: "Not answered yet" or Add
    # A suggested value while it's unanswered (hormone history from the HRT answers). Not saved
    # until the client saves it. prefill_note is shown with it: "We’ve filled this in from your
    # HRT answers. Edit if needed."
    prefill: Any | None
    prefill_note: str | None = None


class SectionOut(BaseModel):
    key: str
    title: str
    # Shown before the section's questions (the follow-up body questions, 6.1).
    privacy_notice: str | None
    questions: list[QuestionOut]
    # Path B's opening line (routing decision 33), shown after the privacy notice: "A few
    # optional questions help me give guidance that fits your body. Skip anything you like."
    intro: str | None = None


class AboutYouOut(BaseModel):
    """Answered at onboarding. Only gender identity and pronouns can be edited here."""

    date_of_birth: date
    age: int
    under_13: bool  # gender labels: label_under_13 from GET /profiles/options (Girl, Boy)
    sex_at_birth: SexAtBirth | None
    gender_identity: GenderIdentity | None
    gender_identity_other: str | None
    pronouns: Pronouns | None  # null: the app shows Add
    pronouns_other: str | None
    editable: list[str]


class HealthProfileOut(BaseModel):
    profile_id: uuid.UUID
    is_self: bool
    first_name: str
    # Story 6.1's heading: "60% complete", or "Complete" with `complete`. Counts only the
    # questions that apply, without optional and sensitive ones or the main wellness goal.
    completion: int
    complete: bool
    about_you: AboutYouOut
    # Only the sections and questions that apply, in order. About you comes first and holds
    # the main wellness goal.
    sections: list[SectionOut]
    # The confirmation the app shows before removing an answer (6.1).
    remove_confirmation: str
    question_bank_version: str


class HealthProfileSaved(BaseModel):
    health_profile: HealthProfileOut
    message: str  # "Thanks, I’ve updated your health profile."
    # Story 6.1's "That’s everything I need. Thank you for taking the time." when this save
    # completed the profile; null otherwise.
    celebration: str | None


class HealthFactOut(BaseModel):
    """A change a logged visit suggests (story 5.2: "the Oracle asks the Client before updating
    their health profile"), for the client to confirm, edit or discard. Details from
    conversations aren't facts: they're saved straight away (3.1, 6 Nov 19:22)."""

    id: uuid.UUID
    profile_id: uuid.UUID
    # The question it answers, including any answer already saved, which confirming replaces.
    question: QuestionOut
    value: Any  # null once discarded
    other: str | None
    conversation_id: uuid.UUID | None
    status: FactStatus
    created_at: datetime


class HealthFactConfirmed(BaseModel):
    fact: HealthFactOut
    message: str
    celebration: str | None
    completion: int


class CircleMapSymptom(BaseModel):
    key: str
    label: str
    # From the profile's symptoms in My Health, including those saved from its conversations.
    highlighted: bool


class CircleMapArea(BaseModel):
    key: str
    label: str
    highlighted: bool  # any of its symptoms is
    symptoms: list[CircleMapSymptom]


class CircleMapOut(BaseModel):
    """Story 6.1's Hypothalamus Circle Map: Deborah's predefined map with the profile's
    symptoms highlighted. The map's areas and symptoms are a placeholder until Deborah's map is
    in (`placeholder` true; app/health/circle_map.json)."""

    profile_id: uuid.UUID
    title: str
    centre: str  # "Hypothalamus"
    # "This map shows how symptoms can connect to the hypothalamus. It isn’t a diagnosis."
    notice: str
    areas: list[CircleMapArea]
    highlighted_count: int
    map_version: str
    placeholder: bool
