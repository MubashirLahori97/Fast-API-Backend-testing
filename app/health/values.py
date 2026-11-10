"""Checking an answer against its question, and showing it as text (story 6.1).

`normalize` turns what the app (or the Oracle, for a proposed fact) sent into the stored form,
{"value": ..., "other": ...}, or raises AnswerProblem with the stories' message. The stored
value by kind:

- choice: a code; multi_choice: a list of codes, in the bank's order;
- checklist: {"selected": [codes], "not_applicable": [codes]};
- text: a cleaned line; number: an int or a float; scale: an int; date: "YYYY-MM-DD";
- named_list: [{"name": ..., "detail": ...}], where [] means "None".

"other" holds the write-in, only with the choice that takes one.
"""

import math
import re
from datetime import date
from typing import Any

from app.core.ages import age_on, today, us_today
from app.core.config import settings
from app.core.schemas import clean_line
from app.health.bank import Question
from app.health.routing import Basics
from app.profiles.schemas import CHOOSE_AN_OPTION

# Story 6.1's "Invalid number" message, for numbers and scales.
INVALID_NUMBER = "That number doesn’t look quite right. Could you check it for me?"
# Not in the stories (docs/decisions/phase-4-health-profile.md).
INVALID_DATE = "That date doesn’t look quite right. Could you check it for me?"
INVALID_ANSWER = "Please check this answer and try again."
WRITE_IN_MISSING = "Tell me a little more in your own words."

_NAME = re.compile(r"\[Name\]")
POSSESSIVE = {"he_him": "his", "she_her": "her"}  # anything else: "their"
OBJECT = {"he_him": "him", "she_her": "her"}  # anything else: "them"


class AnswerProblem(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def fill(text: str | None, basics: Basics) -> str | None:
    """[Name], [their] and [them] for a family member (story 6.1: "Questions use the family
    member’s name and pronouns"). Pronouns other than He/Him and She/Her get the neutral
    words, as story 3.1 asks for Non-binary, Agender and Not listed."""
    if text is None:
        return None
    text = _NAME.sub(basics.first_name, text)
    text = text.replace("[their]", POSSESSIVE.get(basics.pronouns or "", "their"))
    return text.replace("[them]", OBJECT.get(basics.pronouns or "", "them"))


def title(question: Question, basics: Basics) -> str:
    template = question.title if basics.is_self else question.title_family or question.title
    return fill(template, basics)


def _clean(value: Any, *, max_length: int | None = None) -> str:
    if not isinstance(value, str):
        raise AnswerProblem("invalid_answer", INVALID_ANSWER)
    cleaned = clean_line(value)
    limit = max_length or settings.health_text_max_length
    if len(cleaned) > limit:
        raise AnswerProblem("too_long", f"Please keep this to {limit} characters or fewer.")
    return cleaned


def _codes(question: Question, value: Any) -> list[str]:
    """Known codes, once each, in the bank's order."""
    if not isinstance(value, list) or not all(isinstance(code, str) for code in value):
        raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
    if not set(value) <= set(question.codes):
        raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
    return [code for code in question.codes if code in value]


def _write_in(question: Question, chosen: list[str], other: Any, stored: dict) -> None:
    if question.write_in_choice is None or question.write_in_choice not in chosen:
        return
    text = _clean(other) if other is not None else ""
    if text:
        stored["other"] = text
    elif question.write_in_required:
        raise AnswerProblem("write_in_required", question.write_in_message or WRITE_IN_MISSING)


def _number(question: Question, value: Any, basics: Basics, *, integer: bool) -> int | float:
    if isinstance(value, bool):
        raise AnswerProblem("invalid_number", INVALID_NUMBER)
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise AnswerProblem("invalid_number", INVALID_NUMBER) from None
    if not isinstance(value, int | float) or not math.isfinite(value):
        raise AnswerProblem("invalid_number", INVALID_NUMBER)
    if integer and not float(value).is_integer():
        raise AnswerProblem("invalid_number", INVALID_NUMBER)
    if not question.min <= value <= question.max:
        raise AnswerProblem("invalid_number", INVALID_NUMBER)
    if question.up_to_age and value > age_on(basics.date_of_birth, us_today()):
        raise AnswerProblem("invalid_number", INVALID_NUMBER)
    return int(value) if integer else float(value)


def _date(value: Any, basics: Basics) -> str:
    try:
        day = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        day = None
    if day is None or day > today() or day < basics.date_of_birth:
        raise AnswerProblem("invalid_date", INVALID_DATE)
    return day.isoformat()


def _named_list(question: Question, value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AnswerProblem("invalid_answer", INVALID_ANSWER)
    if len(value) > settings.health_list_max_items:
        limit = settings.health_list_max_items
        raise AnswerProblem("too_many", f"Please keep this list to {limit} items or fewer.")
    items = []
    for item in value:
        name = _clean(item.get("name") or "", max_length=settings.name_max_length)
        if not name:
            raise AnswerProblem("name_required", question.missing_name_message)
        detail = _clean(item.get("detail") or "") or None
        items.append({"name": name, "detail": detail})
    return items


def normalize(question: Question, value: Any, other: Any, basics: Basics) -> dict | None:
    """The stored answer, or None when the answer is empty (an empty text): the caller removes
    it, as if the client had cleared the field."""
    stored: dict[str, Any] = {}
    kind = question.kind
    if kind == "choice":
        if not isinstance(value, str) or value not in question.codes:
            raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
        stored["value"] = value
        _write_in(question, [value], other, stored)
    elif kind == "multi_choice":
        chosen = _codes(question, value)
        if not chosen:
            raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
        for code in question.exclusive:
            if code in chosen and len(chosen) > 1:
                label = fill(question.label(code), basics)
                raise AnswerProblem(
                    "exclusive_choice", f"“{label}” can’t be chosen with other answers."
                )
        stored["value"] = chosen
        _write_in(question, chosen, other, stored)
    elif kind == "checklist":
        if not isinstance(value, dict) or not set(value) <= {"selected", "not_applicable"}:
            raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
        selected = _codes(question, value.get("selected") or [])
        not_applicable = _codes(question, value.get("not_applicable") or [])
        if set(selected) & set(not_applicable):
            raise AnswerProblem("invalid_choice", CHOOSE_AN_OPTION)
        stored["value"] = {"selected": selected, "not_applicable": not_applicable}
    elif kind == "text":
        text = _clean(value if value is not None else "")
        if not text:
            return None
        stored["value"] = text
    elif kind == "number":
        stored["value"] = _number(question, value, basics, integer=question.integer)
    elif kind == "scale":
        stored["value"] = _number(question, value, basics, integer=True)
    elif kind == "date":
        stored["value"] = _date(value, basics)
    elif kind == "named_list":
        stored["value"] = _named_list(question, value)
    return stored


def describe(question: Question, answer: dict[str, Any], basics: Basics) -> str:
    """The answer in words, for the Oracle (health_context) and anywhere a line is needed."""
    value, other = answer.get("value"), answer.get("other")

    def labels(codes: list[str]) -> str:
        return ", ".join(fill(question.label(code), basics) for code in codes)

    if question.kind == "choice":
        text = labels([value])
    elif question.kind == "multi_choice":
        text = labels(value)
    elif question.kind == "checklist":
        selected = labels(value.get("selected", [])) or "None of these"
        not_applicable = value.get("not_applicable", [])
        text = f"{selected}; N/A: {labels(not_applicable)}" if not_applicable else selected
    elif question.kind == "named_list":
        items = [
            f"{item['name']} ({item['detail']})" if item.get("detail") else item["name"]
            for item in value
        ]
        text = "; ".join(items) or "None"
    elif question.kind == "scale":
        text = f"{value} out of {int(question.max)}"
    elif question.kind == "number" and question.unit:
        text = f"{value} {question.unit}"
    else:
        text = str(value)
    return f"{text}: {other}" if other else text
