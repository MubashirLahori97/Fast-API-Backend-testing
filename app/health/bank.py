"""The health profile's question bank (story 6.1): the sections, the questions and the rules
that decide which questions apply to a profile.

The bank is data, read from questions.json in this package, or from the file named by
`settings.health_question_bank_path`. The Health Intake Routing document can replace it without
a code change or an app release (6.1's non-functional requirements). It's checked when the app
starts, so a broken file stops the API instead of serving the wrong questions.

A rule (`show_if`, on a section or a question) is a dict of `name: condition`, and every
condition must hold. A name is one of the derived values below, or the key of an earlier
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
- after the "Your body" question only: `body`, the organs the profile has (the "Your body"
  answer, or those assumed from sex at birth when it's skipped), and `body_route`, which body
  questions to ask: female | male | intersex | general.

Section rules may use only the values that don't depend on answers (BASE_NAMES).

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
    "named_list",  # [{"name", "detail"}]: medicines with their reason; [] is "None"
]
CHOICE_KINDS = ("choice", "multi_choice", "checklist")
NUMBER_KINDS = ("number", "scale")

BASE_NAMES = frozenset({"age_group", "age", "sex_at_birth", "gender_identity", "path"})
BODY_NAMES = frozenset({"body", "body_route"})
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


class Prefill(_Strict):
    """A suggested answer taken from another question's answer, shown until the client saves
    their own (6.1: hormone history is pre-filled from the HRT answers)."""

    question: str
    map: dict[str, str]  # the other question's code -> this question's code


class Section(_Strict):
    key: str
    title: str
    title_family: str | None = None
    show_if: dict[str, Any] | None = None
    # The follow-up body questions come after a privacy notice (story 6.1).
    privacy_notice: bool = False


class Question(_Strict):
    key: str
    section: str
    kind: Kind
    title: str
    title_family: str | None = None  # for a family member: "Is [Name] taking..."
    hint: str | None = None
    show_if: dict[str, Any] | None = None

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
    """How the "Your body" answer routes the body questions (stories 3.1 and 6.1): uterus,
    cervix or ovaries mean the female questions, testes or a prostate the male ones, both the
    intersex ones. When it's skipped (or answered with a code in `not_given`), the organs in
    `default` for the sex at birth are assumed, so body questions follow sex at birth."""

    question: str
    female: tuple[str, ...]
    male: tuple[str, ...]
    not_given: tuple[str, ...] = ()
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
    codes = question.codes
    if question.kind in CHOICE_KINDS:
        if len(codes) < (1 if question.kind == "checklist" else 2):
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
        _check_text(f"section {section.key!r}", section.title, section.title_family)
        _check_rule(section.show_if, BASE_NAMES, f"section {section.key!r}")

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
        known = BASE_NAMES | earlier | (BODY_NAMES if body_seen else frozenset())
        _check_rule(question.show_if, frozenset(known), f"question {question.key!r}")
        if question.prefill is not None:
            source = by_key.get(question.prefill.question)
            if (
                question.kind != "choice"
                or source is None
                or source.kind != "choice"
                or not set(question.prefill.map) <= set(source.codes)
                or not set(question.prefill.map.values()) <= set(question.codes)
            ):
                _fail(f"question {question.key!r}", "prefill must map choice codes to codes")
        earlier.add(question.key)
        if question.key == bank.body.question:
            body_seen = True


DEFAULT_PATH = Path(__file__).with_name("questions.json")


def load(path: Path) -> Bank:
    return Bank.model_validate_json(path.read_text(encoding="utf-8"))


BANK = load(
    Path(settings.health_question_bank_path) if settings.health_question_bank_path else DEFAULT_PATH
)
