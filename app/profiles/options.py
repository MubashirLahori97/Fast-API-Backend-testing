"""The answer options for the intake questions and View & edit (stories 2.1, 2.2, 8.1, 8.2).

This module is the one place the options live: the stored codes, the stories' labels and their
order. `GET /profiles/options` serves them, so the apps can show changed labels without a new
release (2.1's non-functional requirements), and `schemas.py` takes its allowed codes from here,
so a code can't be accepted by one and missing from the other.

Labels may contain "[Name]": the app puts the person's first name there, with a capital first
letter (story 2.2).
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Choice:
    code: str  # what the app sends and the database stores
    label: str  # what the app shows
    # Gender only: what a family member under 13 is shown instead (story 2.2 step 6).
    label_under_13: str | None = None
    # A line shown under the label (story 1.5 gives one for a teen's own account).
    description: str | None = None
    # False while the choice can't be picked yet. The app shows it greyed out.
    available: bool = True


@dataclass(frozen=True)
class Question:
    choices: tuple[Choice, ...]
    # The choice that needs a typed answer, and the field the typed answer is sent in.
    write_in_choice: str | None = None
    write_in_field: str | None = None


def codes(question: Question) -> tuple[str, ...]:
    return tuple(choice.code for choice in question.choices)


# Story 2.2 step 1, "Who are they to you?"
FAMILY_RELATIONSHIP = Question(
    choices=(
        Choice("parent", "Parent"),
        Choice("child", "Child"),
        Choice("partner", "Partner"),
        Choice("someone_else", "Someone else"),
    )
)

# Story 2.2's Teen Profile Choice, asked after the date of birth for a member aged 13 up to the
# age of majority. "own_account" skips steps 4 to 7: the privacy disclaimer and the teen's email
# come next, and the invite (story 1.5, POST /profiles/{id}/teen-invite) replaces the draft.
TEEN_PROFILE_CHOICE = Question(
    choices=(
        Choice(
            "own_account",
            "Teen with their own account",
            description="Invite your teen to create their own private Oracle account",
        ),
        Choice("managed", "Manage [Name]’s profile myself"),
    )
)

# Story 2.2 step 4, "Before we set up [Name]’s profile". The option chosen is never shown to
# the support team (2.2's non-functional requirements).
ADVOCATE_CONSENT = Question(
    choices=(
        Choice(
            "agreed",
            "[Name] knows I’m adding them and has agreed for me to be their medical advocate",
        ),
        Choice("parent_or_guardian", "I’m [Name]’s parent or legal guardian"),
        Choice(
            "authorised_to_act",
            "[Name] can’t make this decision themselves, and I’m authorised to act for them "
            "(for example, as their healthcare proxy or power of attorney)",
        ),
    )
)

# Stories 2.1 screen 2 and 2.2 step 5.
SEX_AT_BIRTH = Question(
    choices=(
        Choice("male", "Male"),
        Choice("female", "Female"),
        Choice("intersex", "Intersex"),
        Choice("prefer_not_to_say", "Prefer not to say"),
    )
)

# Stories 2.1 screen 3 and 2.2 step 6. A family member under 13 sees Girl and Boy instead of
# Woman and Man; the codes are the same.
GENDER_IDENTITY = Question(
    choices=(
        Choice("woman", "Woman", label_under_13="Girl"),
        Choice("man", "Man", label_under_13="Boy"),
        Choice("non_binary", "Non-binary"),
        Choice("agender", "Agender"),
        Choice("not_listed", "Not listed"),
        Choice("prefer_not_to_say", "Prefer not to say"),
    ),
    write_in_choice="not_listed",
    write_in_field="gender_identity_other",
)

# Stories 2.1 screen 4 and 2.2 step 7.
PRONOUNS = Question(
    choices=(
        Choice("he_him", "He/Him"),
        Choice("she_her", "She/Her"),
        Choice("they_them", "They/Them"),
        Choice("other", "Other"),
    ),
    write_in_choice="other",
    write_in_field="pronouns_other",
)
# The pronouns selected for the client when the pronoun screen opens, by the gender they chose:
# They/Them for Agender and Not listed (stories 2.1 and 2.2). They can change it.
PRONOUNS_DEFAULT_FOR_GENDER = {"agender": "they_them", "not_listed": "they_them"}

# The questions that take a write-in, by the field that holds the choice.
WRITE_IN_QUESTIONS = {"gender_identity": GENDER_IDENTITY, "pronouns": PRONOUNS}

# The allowed codes, for the request and response schemas.
FamilyRelationship = Literal[*codes(FAMILY_RELATIONSHIP)]
TeenProfileChoice = Literal[*codes(TEEN_PROFILE_CHOICE)]
AdvocateConsent = Literal[*codes(ADVOCATE_CONSENT)]
SexAtBirth = Literal[*codes(SEX_AT_BIRTH)]
GenderIdentity = Literal[*codes(GENDER_IDENTITY)]
Pronouns = Literal[*codes(PRONOUNS)]
