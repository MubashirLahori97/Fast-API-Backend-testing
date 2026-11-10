"""Which sections and questions apply to a profile, and its completion percentage (story 6.1).

Questions are worked through in the bank's order. Each one sees the derived values and the
answers of the earlier questions that apply. An answer to a question that no longer applies is
kept but ignored, so it can't steer the questions after it, isn't shown or counted, and isn't
given to the Oracle; it's used again if the question applies again
(docs/decisions/phase-4-health-profile.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.core.ages import age_group, age_on, us_today
from app.health.bank import BANK, Bank, Question, Section

FollowUpPath = Literal["a", "b", "gender_prefer_not_to_say", "none"]
BodyRoute = Literal["female", "male", "intersex", "general"]

# Gender codes that match each sex at birth. Any other gender differs from it (Path B),
# including Non-binary, Agender and Not listed (question 23).
MATCHING_GENDER = {"male": "man", "female": "woman"}


@dataclass(frozen=True)
class Basics:
    """What routing needs from the profile. About you edits are applied to it before the
    answers are checked, so a gender change in the same save routes them already."""

    is_self: bool
    first_name: str
    date_of_birth: date
    sex_at_birth: str | None
    gender_identity: str | None
    pronouns: str | None


def follow_up_path(sex_at_birth: str | None, gender_identity: str | None) -> FollowUpPath:
    """Stories 3.1 and 6.1. Path A comes first: sex at birth Intersex or Prefer not to say,
    whatever the gender. Then gender Prefer not to say, then Path B: a gender that differs
    from sex at birth."""
    if sex_at_birth in ("intersex", "prefer_not_to_say"):
        return "a"
    if sex_at_birth is None or gender_identity is None:
        return "none"
    if gender_identity == "prefer_not_to_say":
        return "gender_prefer_not_to_say"
    if MATCHING_GENDER.get(sex_at_birth) == gender_identity:
        return "none"
    return "b"


def condition_value(question: Question, answer: Mapping[str, Any]) -> Any:
    """What a show_if rule compares: a code, a list of codes, a number or a text."""
    value = answer.get("value")
    if question.kind == "checklist":
        return list(value.get("selected", [])) if isinstance(value, dict) else []
    if question.kind == "named_list":
        return [item.get("name") for item in value or [] if isinstance(item, dict)]
    return value


def _holds(name: str, condition: dict[str, Any], values: Mapping[str, Any]) -> bool:
    value = values.get(name)
    present = value is not None and value != [] and value != ""
    one = value if isinstance(value, str | int | float) and not isinstance(value, bool) else None
    many = value if isinstance(value, list) else ([value] if one is not None else [])
    for operator, operand in condition.items():
        if operator == "answered" and present != operand:
            return False
        if operator == "in" and (one is None or one not in operand):
            return False
        if operator == "not_in" and one is not None and one in operand:
            return False
        if operator == "has" and not any(item in many for item in operand):
            return False
        if operator == "lacks" and any(item in many for item in operand):
            return False
        if operator == "min" and not (isinstance(one, int | float) and one >= operand):
            return False
        if operator == "max" and not (isinstance(one, int | float) and one <= operand):
            return False
    return True


def matches(rule: Mapping[str, Any] | None, values: Mapping[str, Any]) -> bool:
    if not rule:
        return True
    for name, condition in rule.items():
        if name == "any":
            if not any(matches(sub_rule, values) for sub_rule in condition):
                return False
        elif not _holds(name, condition, values):
            return False
    return True


def body_values(bank: Bank, basics: Basics, body_answer: Any) -> dict[str, Any]:
    """`body` and `body_route` (stories 3.1 and 6.1): the "Your body" answer when it's given,
    otherwise the organs assumed from sex at birth. Uterus, cervix or ovaries route to the
    female questions, testes or a prostate to the male ones, both to the intersex ones; with
    none of them, sex at birth decides, and Prefer not to say gets general questions only."""
    rules = bank.body
    given = [code for code in body_answer or [] if code not in rules.not_given]
    if given:
        organs = given
    else:
        organs = list(rules.default.get(basics.sex_at_birth or "", ()))
    female = any(code in rules.female for code in organs)
    male = any(code in rules.male for code in organs)
    if female and male:
        route: BodyRoute = "intersex"
    elif female:
        route = "female"
    elif male:
        route = "male"
    elif basics.sex_at_birth in ("female", "male", "intersex"):
        route = basics.sex_at_birth
    else:
        route = "general"
    return {"body": organs, "body_route": route}


@dataclass
class Evaluation:
    """The sections and questions that apply, in the bank's order, and their answers."""

    path: FollowUpPath
    sections: list[Section] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    # The saved answers of the questions that apply. Others are kept but not used.
    answers: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    # Derived values and the answers' condition values, as the last question saw them.
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def counted(self) -> list[Question]:
        return [question for question in self.questions if question.counted]

    @property
    def completion(self) -> int:
        """Story 6.1: the share of the counted questions that apply and are answered, rounded
        down, so 100 means every one is answered. Optional and sensitive questions, and the
        main wellness goal (optional), aren't counted."""
        counted = self.counted
        if not counted:
            return 100
        answered = sum(1 for question in counted if question.key in self.answers)
        return answered * 100 // len(counted)

    def applies(self, key: str) -> bool:
        return any(question.key == key for question in self.questions)


def base_values(basics: Basics) -> dict[str, Any]:
    return {
        "age_group": age_group(basics.date_of_birth),
        "age": age_on(basics.date_of_birth, us_today()),
        "sex_at_birth": basics.sex_at_birth,
        "gender_identity": basics.gender_identity,
        "path": follow_up_path(basics.sex_at_birth, basics.gender_identity),
    }


def evaluate(
    basics: Basics, answers: Mapping[str, Mapping[str, Any]], bank: Bank = BANK
) -> Evaluation:
    """`answers` maps question keys to stored answers ({"value", "other"})."""
    base = base_values(basics)
    evaluation = Evaluation(path=base["path"])
    sections = {s.key: s for s in bank.sections if matches(s.show_if, base)}
    evaluation.sections = list(sections.values())
    values = dict(base)
    for question in bank.questions:
        if question.section in sections and matches(question.show_if, values):
            evaluation.questions.append(question)
            answer = answers.get(question.key)
            if answer is not None:
                evaluation.answers[question.key] = answer
                values[question.key] = condition_value(question, answer)
        if question.key == bank.body.question:
            # From here on, rules can use the body. A "Your body" answer that doesn't apply
            # (gender now matches sex at birth) is ignored, so sex at birth decides.
            values.update(body_values(bank, basics, values.get(question.key)))
    evaluation.values = values
    return evaluation
