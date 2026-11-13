"""The health profile's question bank (story 6.1): the sections, the questions and the rules
that decide which questions apply to a profile.

The bank is data, read from questions.json in this package, or from the file named by
`settings.health_question_bank_path`. It follows the BA's Health Intake Routing document
("Revised Intake Routing" tab, Part 3's appendix; docs/decisions/phase-4-routing-doc.md), and a
new version can replace it without a code change or an app release (6.1's non-functional
requirements). It's checked when the app starts, so a broken file stops the API instead of
serving the wrong questions.

A rule (`show_if`, on a section, a question or a choice) is a dict of `name: condition`, and
every condition must hold. A name is one of the derived values below, or the key of an earlier
question (its saved answer). The conditions are:

- {"in": [...]} / {"not_in": [...]}: a single value is (or isn't) one of these. "not_in" also
  holds when there's no value.
- {"has": [...]} / {"lacks": [...]}: a list of values includes any (or none) of these. "lacks"
  also holds when there's no value.
- {"min": n} / {"max": n}: a number is at least / at most n.
- {"answered": true | false}
- And at the top level, "any": [rule, ...]: at least one of these rules holds.

Derived values (routing.py works them out):

- `age_group`: under_13 | teen | adult | 60_plus (app/core/ages.py); `age`: whole years;
- `sex_at_birth` and `gender_identity`: the profile's codes (app/profiles/options.py);
- `path`: which follow-up body questions apply (story 6.1): "a" (sex at birth Intersex or
  Prefer not to say), "b" (gender differs from sex at birth), "gender_prefer_not_to_say", or
  "none" (gender matches sex at birth);
- `teen_own_login`: "yes" for a teen's own profile on a teen account (users.account_type
  'teen', story 1.5), "no" otherwise (routing decision 43: sexual health only for them);
- after the "Your body" question only: `body`, the organs the profile has (the ticked ones, or
  those assumed from sex at birth when it's skipped), `body_ticked`, only the ticked ones
  ([] when skipped), and `body_route`, which body questions to ask: female | male | intersex |
  general.

Section rules, variants and section intros may use only the values that don't depend on
answers (BASE_NAMES).

Each question also says when it's asked (`when_asked`, Part 3's column): "asked_first" (the
first time it's relevant), "asked_later" (only when it helps the concern), "conversation" (the
follow-up body questions, asked in conversation) or "onboarding". Every question can also be
answered in My Health. `conversation_if` narrows when the Oracle may ask it in conversation
(decision 42: "Your body" is in everyone's My Health, but asked in conversation only in Path A,
Path B and gender Prefer not to say). `variants` change a question's wording, when it's asked
or its columns by age group (the first that matches wins).

Titles and labels may contain [Name], [their] and [them]: the service fills them in from the
profile's first name and pronouns.
"""

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

from app.core.config import settings
from app.profiles import options

Kind = Literal[
    "choice",  # one code; "other" holds the write-in
    "multi_choice",  # a list of codes
    "checklist",  # {"selected": [codes], "not_applicable": [codes]}: symptoms, with N/A
    "text",
    "number",
    "scale",  # a whole number from min to max
    "date",  # an ISO date, not in the future or before the date of birth
    "time",  # "HH:MM", 24-hour (bedtime, wake time)
    "named_list",  # [{"name", "detail"}]: medicines with their reason; [] is "None"
    # Medical history: {"self": {code: detail | null}, "family": {code: detail | null}}, only
    # the question's columns; ticking an item opens a short text (Part 3).
    "history",
]
CHOICE_KINDS = ("choice", "multi_choice", "checklist", "history")
NUMBER_KINDS = ("number", "scale")
WhenAsked = Literal["onboarding", "asked_first", "asked_later", "conversation"]
Column = Literal["self", "family"]

BASE_NAMES = frozenset(
    {"age_group", "age", "sex_at_birth", "gender_identity", "path", "teen_own_login"}
)
BODY_NAMES = frozenset({"body", "body_ticked", "body_route"})
OPERATORS = frozenset({"in", "not_in", "has", "lacks", "min", "max", "answered"})
PLACEHOLDERS = frozenset({"Name", "their", "them"})
ABOUT_YOU = "about_you"  # the section the service adds the profile's own fields to

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_PLACEHOLDER = re.compile(r"\[([^\]]+)\]")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Choice(_Strict):
    code: str
    label: str
    # Shown only when this holds (for example the female-body items of the medical history);
    # an answer can't use a choice that isn't shown.
    show_if: dict[str, Any] | None = None


class Prefill(_Strict):
    """A suggested answer taken from another question's answer, shown until the client saves
    their own (6.1 and Part 3: hormone history is pre-filled from the HRT answers)."""

    question: str
    # The other question's code -> this question's codes. For a choice question, the
    # suggestion is used only when it comes to exactly one code.
    map: dict[str, tuple[str, ...]]
    note: str | None = None  # shown with the suggestion


class Variant(_Strict):
    """Different wording, timing or columns for some profiles, by the values that don't depend
    on answers (for example the under-13 wording of the medicines question)."""

    show_if: dict[str, Any]
    title: str | None = None
    title_family: str | None = None
    when_asked: WhenAsked | None = None
    columns: tuple[Column, ...] | None = None


class Section(_Strict):
    key: str
    title: str
    title_family: str | None = None
    show_if: dict[str, Any] | None = None
    # The follow-up body questions come after a privacy notice (story 6.1).
    privacy_notice: bool = False
    # A line shown before the section's questions when intro_show_if holds (Path B's opening
    # line, routing decision 33).
    intro: str | None = None
    intro_show_if: dict[str, Any] | None = None


class Question(_Strict):
    key: str
    section: str
    kind: Kind
    title: str
    title_family: str | None = None  # for a family member: "Is [Name] taking..."
    hint: str | None = None
    show_if: dict[str, Any] | None = None
    when_asked: WhenAsked
    # The Oracle asks it in conversation only when this holds too (My Health shows it whenever
    # show_if holds).
    conversation_if: dict[str, Any] | None = None
    variants: tuple[Variant, ...] = ()
    # history: the columns offered (teens and children: family only, through a variant).
    columns: tuple[Column, ...] = ("self", "family")

    # Choice kinds.
    choices: tuple[Choice, ...] = ()
    # multi_choice: codes that can't be chosen with any other ("None of these").
    exclusive: tuple[str, ...] = ()
    # choice and multi_choice: the code that takes a typed answer ("Other: ____").
    write_in_choice: str | None = None
    write_in_label: str | None = None
    write_in_required: bool = False
    write_in_message: str | None = None

    # number and scale.
    min: float | None = None
    max: float | None = None
    integer: bool = False
    up_to_age: bool = False  # can't be more than the profile's age ("age at first period")
    unit: str | None = None
    min_label: str | None = None  # scale
    max_label: str | None = None

    # named_list.
    name_label: str | None = None
    detail_label: str | None = None
    missing_name_message: str | None = None

    # Optional and sensitive questions aren't counted in the completion percentage (6.1).
    optional: bool = False
    sensitive: bool = False
    prefill: Prefill | None = None

    @property
    def counted(self) -> bool:
        return not (self.optional or self.sensitive)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(choice.code for choice in self.choices)

    def label(self, code: str) -> str:
        return next((c.label for c in self.choices if c.code == code), code)


class BodyRules(_Strict):
    """How the "Your body" answer routes the body questions (routing document, Part 1): a
    uterus or ovaries mean the female questions, testes or a prostate the male ones, both the
    intersex ones, and none of them (including "None of these") general questions only. When
    it's skipped (or answered with a code in `not_given`), the organs in `default` for the sex
    at birth are assumed, so body questions follow sex at birth."""

    question: str
    female: tuple[str, ...]
    male: tuple[str, ...]
    none: tuple[str, ...] = ()  # "None of these": answered, with no organs
    not_given: tuple[str, ...] = ()  # "Prefer not to say": as if skipped
    default: dict[str, tuple[str, ...]] = {}


class Bank(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=False)

    version: str
    status: str
    note: str | None = None
    body: BodyRules
    sections: tuple[Section, ...]
    questions: tuple[Question, ...]

    _questions: dict[str, Question] = PrivateAttr(default_factory=dict)
    _sections: dict[str, Section] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any) -> None:
        self._questions = {question.key: question for question in self.questions}
        self._sections = {section.key: section for section in self.sections}

    def question(self, key: str) -> Question | None:
        return self._questions.get(key)

    def section(self, key: str) -> Section:
        return self._sections[key]

    @model_validator(mode="after")
    def check(self) -> "Bank":
        _check_bank(self)
        return self


def _fail(where: str, problem: str) -> None:
    raise ValueError(f"{where}: {problem}")


def _check_text(where: str, *texts: str | None) -> None:
    for text in texts:
        for token in _PLACEHOLDER.findall(text or ""):
            if token not in PLACEHOLDERS:
                _fail(where, f"unknown placeholder [{token}]")


def _check_rule(rule: Any, known: frozenset[str], where: str) -> None:
    if rule is None:
        return
    if not isinstance(rule, dict):
        _fail(where, "show_if must be an object")
    for name, condition in rule.items():
        if name == "any":
            if not isinstance(condition, list) or not condition:
                _fail(where, '"any" must be a non-empty list of rules')
            for sub_rule in condition:
                _check_rule(sub_rule, known, where)
            continue
        if name not in known:
            _fail(where, f"show_if uses {name!r}: not a derived value or an earlier question")
        if not isinstance(condition, dict) or not condition:
            _fail(where, f"the condition on {name!r} must be a non-empty object")
        for operator, operand in condition.items():
            if operator not in OPERATORS:
                _fail(where, f"unknown operator {operator!r}")
            if operator in ("in", "not_in", "has", "lacks") and not isinstance(operand, list):
                _fail(where, f"{operator!r} takes a list")
            if operator in ("min", "max") and not isinstance(operand, int | float):
                _fail(where, f"{operator!r} takes a number")
            if operator == "answered" and not isinstance(operand, bool):
                _fail(where, '"answered" takes true or false')


def _check_question(question: Question) -> None:
    where = f"question {question.key!r}"
    if not _KEY.match(question.key):
        _fail(where, "keys are lower snake_case")
    if question.key in BASE_NAMES | BODY_NAMES or question.key == "any":
        _fail(where, "the key is a derived value's name")
    _check_text(where, question.title, question.title_family, question.hint)
    for variant in question.variants:
        _check_rule(variant.show_if, BASE_NAMES, where)
        _check_text(where, variant.title, variant.title_family)
        if variant.columns is not None and (question.kind != "history" or not variant.columns):
            _fail(where, "only a history question's variants set columns")
    if question.kind == "history" and not question.columns:
        _fail(where, "a history question needs columns")
    codes = question.codes
    if question.kind in CHOICE_KINDS:
        if len(codes) < (1 if question.kind in ("checklist", "history") else 2):
            _fail(where, "needs more choices")
        if len(set(codes)) != len(codes):
            _fail(where, "choice codes repeat")
        _check_text(where, *(choice.label for choice in question.choices))
    elif codes:
        _fail(where, f"a {question.kind} question has no choices")
    if question.exclusive and (
        question.kind != "multi_choice" or not set(question.exclusive) <= set(codes)
    ):
        _fail(where, "exclusive codes must be choices of a multi_choice question")
    if question.write_in_choice is not None and (
        question.kind not in ("choice", "multi_choice") or question.write_in_choice not in codes
    ):
        _fail(where, "write_in_choice must be a choice of a choice or multi_choice question")
    if question.kind in NUMBER_KINDS:
        if question.min is None or question.max is None or question.min >= question.max:
            _fail(where, "needs min below max")
        if question.kind == "scale" and not (
            float(question.min).is_integer() and float(question.max).is_integer()
        ):
            _fail(where, "a scale runs between whole numbers")
    if question.kind == "named_list" and not question.missing_name_message:
        _fail(where, "a named_list needs missing_name_message")


def _check_bank(bank: Bank) -> None:
    section_keys = [section.key for section in bank.sections]
    if len(set(section_keys)) != len(section_keys):
        _fail("sections", "keys repeat")
    if ABOUT_YOU not in section_keys:
        _fail("sections", f"the {ABOUT_YOU!r} section is required")
    for section in bank.sections:
        _check_text(f"section {section.key!r}", section.title, section.title_family, section.intro)
        _check_rule(section.show_if, BASE_NAMES, f"section {section.key!r}")
        _check_rule(section.intro_show_if, BASE_NAMES, f"section {section.key!r}")

    question_keys = [question.key for question in bank.questions]
    if len(set(question_keys)) != len(question_keys):
        _fail("questions", "keys repeat")
    by_key = {question.key: question for question in bank.questions}

    body = by_key.get(bank.body.question)
    if body is None or body.kind != "multi_choice":
        _fail("body", "question must be a multi_choice question in the bank")
    for codes in (
        bank.body.female,
        bank.body.male,
        bank.body.none,
        bank.body.not_given,
        *bank.body.default.values(),
    ):
        if not set(codes) <= set(body.codes):
            _fail("body", "organ codes must be choices of the body question")
    if not set(bank.body.default) <= set(options.codes(options.SEX_AT_BIRTH)):
        _fail("body", "default is keyed by sex at birth codes")

    earlier: set[str] = set()
    body_seen = False
    for question in bank.questions:
        _check_question(question)
        if question.section not in section_keys:
            _fail(f"question {question.key!r}", f"unknown section {question.section!r}")
        known = frozenset(BASE_NAMES | earlier | (BODY_NAMES if body_seen else frozenset()))
        where = f"question {question.key!r}"
        _check_rule(question.show_if, known, where)
        _check_rule(question.conversation_if, known, where)
        for choice in question.choices:
            _check_rule(choice.show_if, known, where)
        if question.prefill is not None:
            source = by_key.get(question.prefill.question)
            mapped = {code for codes in question.prefill.map.values() for code in codes}
            if (
                question.kind not in ("choice", "multi_choice")
                or source is None
                or source.kind not in ("choice", "multi_choice")
                or not set(question.prefill.map) <= set(source.codes)
                or not mapped <= set(question.codes)
            ):
                _fail(where, "prefill must map choice codes to codes")
            _check_text(where, question.prefill.note)
        earlier.add(question.key)
        if question.key == bank.body.question:
            body_seen = True


DEFAULT_PATH = Path(__file__).with_name("questions.json")


def load(path: Path) -> Bank:
    return Bank.model_validate_json(path.read_text(encoding="utf-8"))


BANK = load(
    Path(settings.health_question_bank_path) if settings.health_question_bank_path else DEFAULT_PATH
)
