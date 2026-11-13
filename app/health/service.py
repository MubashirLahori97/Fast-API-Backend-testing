"""My Health (story 6.1): viewing, editing and completing a profile's health profile, the
details the Oracle saves from conversations (3.1, 3.3), and the changes a logged visit suggests,
which the client confirms first (5.2).

Which questions apply comes from the question bank (bank.py, questions.json) through
routing.py. Answers are health data: never logged, and audit events record only how many
answers changed and where the change came from (the client or a conversation).

For the conversations package:

- `health_context(db, profile, account)`: the answered questions that apply, for the Oracle;
- `open_questions(db, profile, account)`: those still to answer that it may ask in
  conversation, so it can ask them when they're relevant and save answers with the right codes;
- `oracle_view(db, profile, account)`: both, with the routing (follow-up path, body route and
  Path B's opening line), from one read;
- `save_from_conversation(...)` and `record_conversation_saves(...)`: save what the Oracle
  learned straight away, marked as added from the conversation (the 6 Nov 19:22 stories: the
  client accepted the Health Consent, so nothing is confirmed first).

For the guidance summary (3.3): `added_from_conversation(db, profile, account, conversation_id)`
lists what was added from a conversation, for "Here’s what I’ve added to your health profile...".

For visits (5.2): `propose_fact(...)` saves a suggested change as a pending fact, which the
client confirms or discards before the profile changes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import entitlements
from app.conversations.widgets import PRIVACY_NOTICE_TEXT
from app.core import audit
from app.core.ages import age_group, age_on, today
from app.core.config import settings
from app.core.errors import AppError
from app.health import circle_map, reminders
from app.health.bank import ABOUT_YOU, BANK, Question, Section
from app.health.models import HealthAnswer, HealthFact, HealthProfile
from app.health.routing import (
    Basics,
    Evaluation,
    columns,
    evaluate,
    hidden_choice,
    visible_codes,
    when_asked,
)
from app.health.routing import matches as rule_matches
from app.health.schemas import (
    AboutYouEdit,
    AboutYouOut,
    AnswerIn,
    AnswerOut,
    ChoiceOut,
    CircleMapArea,
    CircleMapOut,
    CircleMapSymptom,
    HealthFactConfirmed,
    HealthFactOut,
    HealthProfileEdit,
    HealthProfileOut,
    HealthProfileSaved,
    QuestionOut,
    SectionOut,
)
from app.health.values import AnswerProblem, describe, fill, normalize, title
from app.profiles import options
from app.profiles.models import Profile
from app.profiles.schemas import CHOOSE_AN_OPTION
from app.profiles.service import check_can_use
from app.wellness import triggers as wellness_triggers

# Story 6.1's messages.
MY_HEALTH_LOCKED = "My Health is part of your plan. Choose a plan to unlock it."
CHANGES_SAVED = "Thanks, I’ve updated your health profile."
PROFILE_COMPLETE = "That’s everything I need. Thank you for taking the time."
SAVE_FAILED = "We couldn’t save your changes just now. Please try again."
REMOVE_CONFIRMATION = "Remove this answer? I won’t use it in your guidance any more."
READ_ONLY_SELF = (
    "Your date of birth and sex assigned at birth can’t be changed here. "
    "If something is wrong, please contact the support team."
)
# Not in the stories (docs/decisions/phase-4-health-profile.md).
UNKNOWN_QUESTION = "We couldn’t find that question. Please refresh and try again."
UNKNOWN_SECTION = "We couldn’t find that section. Please refresh and try again."
NOT_APPLICABLE = "This question doesn’t apply to this profile."
FACT_NOT_FOUND = "We couldn’t find that health detail."
FACT_ALREADY_DISCARDED = "This was already dismissed, so it can’t be saved."
FACT_ALREADY_SAVED = "This is already saved to the health profile. You can change it in My Health."

EDITABLE_ABOUT_YOU = ["gender_identity", "pronouns"]


def check_my_health_unlocked(account: User) -> None:
    """Story 6.1 (and 9.1): My Health is greyed out during the free trial (and after an ended
    subscription), with the upgrade prompt. app/billing/entitlements.py decides; the message
    is 6.1's own, rather than 9.1's general "This is part of your plan..."."""
    if entitlements.feature_access(account)["my_health"]:
        raise AppError(403, "upgrade_required", MY_HEALTH_LOCKED)


@contextmanager
def _saving(db: Session) -> Iterator[None]:
    """Story 6.1's "Save failed" message for any database error. The error's own text isn't
    logged or returned: it can contain the answers."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", SAVE_FAILED) from None


def basics(profile: Profile, account: User | None = None) -> Basics:
    """The profile's routing inputs. Only for a usable profile, which has a date of birth."""
    if profile.is_self:
        name = account.first_name if account is not None else ""
    else:
        name = profile.first_name or ""
    return Basics(
        is_self=profile.is_self,
        first_name=name,
        date_of_birth=profile.date_of_birth,
        sex_at_birth=profile.sex_at_birth,
        gender_identity=profile.gender_identity,
        pronouns=profile.pronouns,
        # Routing decision 43: a teen's own profile on a teen account (story 1.5).
        teen_own_login=(profile.is_self and account is not None and account.account_type == "teen"),
        state=profile.majority_state,
    )


def _answers(db: Session, profile: Profile) -> dict[str, HealthAnswer]:
    rows = db.scalars(select(HealthAnswer).where(HealthAnswer.profile_id == profile.id))
    return {row.question_key: row for row in rows}


def _stored(rows: dict[str, HealthAnswer]) -> dict[str, dict]:
    return {key: row.answer for key, row in rows.items()}


def _evaluate(db: Session, profile: Profile, account: User | None) -> Evaluation:
    return evaluate(basics(profile, account), _stored(_answers(db, profile)))


# Viewing


def _answer_out(row: HealthAnswer) -> AnswerOut:
    return AnswerOut(
        value=row.answer.get("value"),
        other=row.answer.get("other"),
        source=row.source,
        conversation_id=row.conversation_id,
        updated_at=row.updated_at,
        added_from_conversation_at=row.updated_at if row.source == "conversation" else None,
    )


def _prefill(question: Question, evaluation: Evaluation) -> Any:
    """The suggestion taken from another answer (hormone history from the HRT answers, 6.1 and
    the routing document's Part 3), in the form this question saves, or None."""
    if question.prefill is None:
        return None
    source = evaluation.answers.get(question.prefill.question)
    if source is None:
        return None
    value = source.get("value")
    chosen = value if isinstance(value, list) else [value]
    mapped = {code for picked in chosen for code in question.prefill.map.get(picked, ())}
    codes = [code for code in question.codes if code in mapped]
    if question.kind == "multi_choice":
        return codes or None
    return codes[0] if len(codes) == 1 else None


def question_out(
    question: Question, person: Basics, row: HealthAnswer | None, evaluation: Evaluation
) -> QuestionOut:
    shown = visible_codes(question, evaluation.values)
    prefill = _prefill(question, evaluation) if row is None else None
    return QuestionOut(
        key=question.key,
        kind=question.kind,
        title=title(question, person),
        hint=fill(question.hint, person),
        when_asked=when_asked(question, evaluation.base),
        choices=[
            ChoiceOut(code=c.code, label=fill(c.label, person))
            for c in question.choices
            if c.code in shown
        ],
        exclusive=list(question.exclusive),
        write_in_choice=question.write_in_choice,
        write_in_label=fill(question.write_in_label, person),
        write_in_required=question.write_in_required,
        min=question.min,
        max=question.max,
        integer=question.integer or question.kind == "scale",
        unit=question.unit,
        min_label=question.min_label,
        max_label=question.max_label,
        name_label=question.name_label,
        detail_label=question.detail_label,
        columns=list(columns(question, evaluation.base)) if question.kind == "history" else [],
        optional=question.optional,
        sensitive=question.sensitive,
        counted=question.counted,
        answer=_answer_out(row) if row is not None else None,
        prefill=prefill,
        prefill_note=question.prefill.note if prefill is not None else None,
    )


def _section_title(section: Section, person: Basics) -> str:
    template = section.title if person.is_self else section.title_family or section.title
    return fill(template, person)


def _section_intro(section: Section, person: Basics, evaluation: Evaluation) -> str | None:
    """Path B's opening line (routing decision 33), where the follow-ups are offered."""
    if section.intro is None or not rule_matches(section.intro_show_if, evaluation.base):
        return None
    return fill(section.intro, person)


def health_profile_out(db: Session, profile: Profile, account: User) -> HealthProfileOut:
    """Only the sections and questions that apply to the profile now, with their answers.
    Answers kept from questions that no longer apply aren't shown."""
    rows = _answers(db, profile)
    person = basics(profile, account)
    evaluation = evaluate(person, _stored(rows))
    sections = []
    for section in evaluation.sections:
        questions = [
            question_out(question, person, rows.get(question.key), evaluation)
            for question in evaluation.questions
            if question.section == section.key
        ]
        if not questions and section.key != ABOUT_YOU:
            continue
        sections.append(
            SectionOut(
                key=section.key,
                title=_section_title(section, person),
                privacy_notice=PRIVACY_NOTICE_TEXT if section.privacy_notice else None,
                questions=questions,
                intro=_section_intro(section, person, evaluation),
            )
        )
    completion = evaluation.completion
    return HealthProfileOut(
        profile_id=profile.id,
        is_self=profile.is_self,
        first_name=person.first_name,
        completion=completion,
        complete=completion == 100,
        about_you=AboutYouOut(
            date_of_birth=profile.date_of_birth,
            age=age_on(profile.date_of_birth, today()),
            under_13=not profile.is_self
            and age_group(profile.date_of_birth, profile.majority_state) == "under_13",
            sex_at_birth=profile.sex_at_birth,
            gender_identity=profile.gender_identity,
            gender_identity_other=profile.gender_identity_other,
            pronouns=profile.pronouns,
            pronouns_other=profile.pronouns_other,
            editable=EDITABLE_ABOUT_YOU,
        ),
        sections=sections,
        remove_confirmation=REMOVE_CONFIRMATION,
        question_bank_version=BANK.version,
    )


def get_health_profile(db: Session, profile: Profile, account: User) -> HealthProfileOut:
    check_my_health_unlocked(account)
    return health_profile_out(db, profile, account)


def completion(db: Session, profile: Profile) -> int | None:
    """The completion percentage, for Manage Family's cards (8.2) and the dashboard (4.1).
    None for a profile whose intake isn't finished."""
    if profile.intake_completed_at is None or profile.date_of_birth is None:
        return None
    return _evaluate(db, profile, None).completion


def last_updated_at(db: Session, profile: Profile) -> datetime | None:
    """When the health profile last changed (the intake counts), for 4.1's "Update your health
    profile" widget: shown 3, 6 or 12 months after it, or after a logged visit."""
    row = db.get(HealthProfile, profile.id)
    return row.updated_at if row is not None else None


# The Hypothalamus Circle Map (story 6.1)


def _map_items(db: Session, profile: Profile, account: User) -> set[tuple[str, str]]:
    """The symptoms ticked in the questions that apply: from My Health and from conversations,
    which the Oracle saves into the same answers (3.1)."""
    return circle_map.ticked(dict(_evaluate(db, profile, account).answers))


def get_circle_map(db: Session, profile: Profile, account: User) -> CircleMapOut:
    """Part of My Health, so greyed out during the free trial like the rest of it."""
    check_my_health_unlocked(account)
    items = _map_items(db, profile, account)
    areas = []
    for area in circle_map.MAP.areas:
        symptoms = [
            CircleMapSymptom(
                key=symptom.key,
                label=symptom.label,
                highlighted=circle_map.highlighted(symptom, items),
            )
            for symptom in area.symptoms
        ]
        areas.append(
            CircleMapArea(
                key=area.key,
                label=area.label,
                highlighted=any(symptom.highlighted for symptom in symptoms),
                symptoms=symptoms,
            )
        )
    return CircleMapOut(
        profile_id=profile.id,
        title=circle_map.MAP.title,
        centre=circle_map.MAP.centre,
        notice=circle_map.NOTICE,
        areas=areas,
        highlighted_count=sum(s.highlighted for area in areas for s in area.symptoms),
        map_version=circle_map.MAP.version,
        placeholder=circle_map.MAP.placeholder,
    )


def circle_map_pdf(db: Session, profile: Profile, account: User) -> tuple[bytes, str]:
    """The map to download or print (6.1), made on request and never stored."""
    check_my_health_unlocked(account)
    items = _map_items(db, profile, account)
    return circle_map.to_pdf(basics(profile, account).first_name, items), circle_map.FILE_NAME


# Editing


def _read_only_message(profile: Profile, name: str) -> str:
    if profile.is_self:
        return READ_ONLY_SELF
    return (
        f"{name}’s date of birth and sex assigned at birth can’t be changed here. "
        "If something is wrong, please contact the support team."
    )


def _write_in_message(profile: Profile, name: str, field: str) -> str:
    """6.1's wording for the client's own profile, 8.2's (with the name) for a family member."""
    if field == "gender_identity_other":
        if profile.is_self:
            return "Tell me in your own words how you identify."
        return f"Tell me in your own words how {name} identifies."
    if profile.is_self:
        return "Tell me which pronouns you’d like me to use."
    return f"Tell me which pronouns you’d like me to use for {name}."


def _about_you_changes(
    profile: Profile, person: Basics, about: AboutYouEdit | None
) -> dict[str, Any]:
    """The About you fields that change. Gender identity and pronouns only; a write-in goes
    with the sent choice, or the saved one if only the write-in was sent, and is cleared for a
    choice that takes none (as in 8.2's View & edit)."""
    if about is None:
        return {}
    for field in ("date_of_birth", "sex_at_birth"):
        value = getattr(about, field)
        if value is not None and value != getattr(profile, field):
            raise AppError(422, "read_only", _read_only_message(profile, person.first_name), field)
    sent = about.model_fields_set
    changed: dict[str, Any] = {}
    for choice, question in options.WRITE_IN_QUESTIONS.items():
        write_in = question.write_in_field
        new_choice = getattr(about, choice)
        if new_choice is None and write_in not in sent:
            continue
        if new_choice is not None and new_choice != getattr(profile, choice):
            changed[choice] = new_choice
        chosen = new_choice if new_choice is not None else getattr(profile, choice)
        value = getattr(about, write_in) if write_in in sent else getattr(profile, write_in)
        if chosen != question.write_in_choice:
            value = None
        elif not value:
            message = _write_in_message(profile, person.first_name, write_in)
            raise AppError(422, "write_in_required", message, write_in)
        if value != getattr(profile, write_in):
            changed[write_in] = value
    return changed


def _refuse(problems: list[tuple[str, str, str]]) -> None:
    """One error for every refused answer, the first one's message on top."""
    field, code, message = problems[0]
    details = [{"field": f, "message": m} for f, _, m in problems] if len(problems) > 1 else None
    raise AppError(422, code, message, field, details=details)


def _record_update(
    db: Session,
    profile: Profile,
    account: User,
    request: Request | None,
    source: str,
    saved: int,
    removed: int,
    fields: list[str] | None = None,
) -> None:
    """Story 6.1: every change is logged with its date and whether it came from the client or
    a conversation (kept 6 years, BAA Section 13). How many answers changed, never which ones
    or their values: a question's key alone can say which body questions a person gets."""
    details: dict[str, Any] = {"source": source, "answers_saved": saved, "answers_removed": removed}
    if fields:
        details["fields"] = fields
    audit.record(
        db,
        "health_profile.updated",
        actor_id=account.id,
        target_type="profile",
        target_id=profile.id,
        request=request,
        details=details,
    )
    reminders.record_update(db, account, profile)
    wellness_triggers.health_profile_changed(db, account, profile)  # Phase 7: plan update (7.1)


def save_health_profile(
    db: Session, profile: Profile, edit: HealthProfileEdit, account: User, request: Request
) -> HealthProfileSaved:
    """Saves a section's Edit or a step of Complete my profile. Questions that start to apply
    appear in the answer, and ones that stop applying are hidden; their answers are kept but
    not shown, counted or used, and come back if the question applies again."""
    check_my_health_unlocked(account)
    with _saving(db):
        db.refresh(profile, with_for_update=True)  # one save per profile at a time
        check_can_use(profile)
        rows = _answers(db, profile)
        person = basics(profile, account)
        before = evaluate(person, _stored(rows)).completion

        about = _about_you_changes(profile, person, edit.about_you)
        person = replace(
            person,
            gender_identity=about.get("gender_identity", person.gender_identity),
            pronouns=about.get("pronouns", person.pronouns),
        )

        problems: list[tuple[str, str, str]] = []
        for section in edit.remove_sections:
            if section not in {s.key for s in BANK.sections}:
                problems.append((f"remove_sections.{section}", "unknown_section", UNKNOWN_SECTION))
        new: dict[str, dict | None] = {}
        for key, sent in edit.answers.items():
            question = BANK.question(key)
            if question is None:
                problems.append((f"answers.{key}", "unknown_question", UNKNOWN_QUESTION))
                continue
            if sent is None or sent.value is None:
                new[key] = None
                continue
            try:
                new[key] = normalize(question, sent.value, sent.other, person)
            except AnswerProblem as problem:
                problems.append((f"answers.{key}", problem.code, problem.message))

        # Answers in the removed sections, unless this save gives them a new value.
        removing = {
            key
            for key, row in rows.items()
            if (question := BANK.question(key)) is not None
            and question.section in edit.remove_sections
            and new.get(key) is None
        }
        merged = {key: row.answer for key, row in rows.items() if key not in removing}
        for key, value in new.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        evaluation = evaluate(person, merged)
        for key, value in new.items():
            if value is None:
                continue
            if not evaluation.applies(key):
                problems.append((f"answers.{key}", "not_applicable", NOT_APPLICABLE))
            elif hidden_choice(BANK.question(key), value, evaluation.values):
                # A choice this profile isn't shown (for example an adult-only status).
                problems.append((f"answers.{key}", "invalid_choice", CHOOSE_AN_OPTION))
        if problems:
            _refuse(problems)

        saved = removed = 0
        for key, value in new.items():
            row = rows.get(key)
            if value is None:
                removing.add(key)
            elif row is None:
                db.add(
                    HealthAnswer(
                        profile_id=profile.id, question_key=key, answer=value, source="client"
                    )
                )
                saved += 1
            elif row.answer != value or row.source != "client":
                row.answer = value
                row.source = "client"
                row.conversation_id = None
                saved += 1
        for key in removing:
            if key in rows:
                db.delete(rows[key])
                removed += 1
        for field, value in about.items():
            setattr(profile, field, value)
        if saved or removed or about:
            fields = sorted({field.removesuffix("_other") for field in about})
            _record_update(db, profile, account, request, "client", saved, removed, fields)
        db.commit()

    after = evaluation.completion
    return HealthProfileSaved(
        health_profile=health_profile_out(db, profile, account),
        message=CHANGES_SAVED,
        celebration=PROFILE_COMPLETE if after == 100 and before < 100 else None,
    )


# For the Oracle (the conversations package passes these on through app/oracle/contract.py)


@dataclass(frozen=True)
class KnownAnswer:
    """One answered question that applies to the profile. Health data, like everything given
    to the Oracle; the text came from the client, so it's data, never instructions."""

    key: str
    section: str
    question: str  # worded for the profile ("Is Azka taking any medications?")
    answer: str  # in words
    value: Any  # the stored codes or value (app/health/values.py)
    other: str | None
    sensitive: bool
    from_conversation: bool  # saved by the Oracle from a conversation, unchanged since
    updated_at: datetime  # so it can check an old answer instead of asking again (3.1)


@dataclass(frozen=True)
class OpenQuestion:
    """A question that applies and isn't answered yet."""

    key: str
    section: str
    question: str
    kind: str
    choices: tuple[tuple[str, str], ...]  # (code, label), only those shown to the profile
    write_in_choice: str | None
    optional: bool
    sensitive: bool
    when_asked: str  # asked_first | asked_later | conversation | onboarding (Part 3)


@dataclass(frozen=True)
class Routing:
    """How the profile's questions are routed (routing document, Part 1), for the Oracle."""

    follow_up_path: str  # a | b | gender_prefer_not_to_say | none
    body_route: str  # female | male | intersex | general
    organs: tuple[str, ...]  # the "Your body" codes it routes by (ticked, or from sex at birth)
    body_from_your_body: bool  # False: "Your body" wasn't answered, so sex at birth decides
    opening_line: str | None  # Path B's opening line (decision 33), else None


@dataclass(frozen=True)
class OracleView:
    known: list["KnownAnswer"]
    open: list[OpenQuestion]
    routing: Routing


def health_context(db: Session, profile: Profile, account: User) -> list[KnownAnswer]:
    """Only the answered questions that apply, in the bank's order (story 3.1: "Everything
    already answered", and "Never repeat"). Removed answers and answers kept from questions
    that no longer apply aren't included, so the Oracle stops using them (6.1). The About you
    fields are already in the contract's ProfileContext."""
    rows = _answers(db, profile)
    person = basics(profile, account)
    return _known(evaluate(person, _stored(rows)), rows, person)


def _known(
    evaluation: Evaluation, rows: dict[str, HealthAnswer], person: Basics
) -> list[KnownAnswer]:
    known = []
    for question in evaluation.questions:
        row = rows.get(question.key)
        if row is None:
            continue
        known.append(
            KnownAnswer(
                key=question.key,
                section=question.section,
                question=title(question, person),
                answer=describe(question, row.answer, person),
                value=row.answer.get("value"),
                other=row.answer.get("other"),
                sensitive=question.sensitive,
                from_conversation=row.source == "conversation",
                updated_at=row.updated_at,
            )
        )
    return known


def open_questions(db: Session, profile: Profile, account: User) -> list[OpenQuestion]:
    """The questions the Oracle may still ask when they're relevant (6.1: "The Oracle also asks
    these questions in conversation"), with the codes a health_fact takes. Only those it may
    ask in conversation: "Your body" is in every client's My Health, but the Oracle asks it only
    in Path A, Path B and gender Prefer not to say (routing decision 42)."""
    return _open(_evaluate(db, profile, account), basics(profile, account))


def _open(evaluation: Evaluation, person: Basics) -> list[OpenQuestion]:
    open_ = []
    for question in evaluation.questions:
        if question.key in evaluation.answers or not evaluation.asked_in_conversation(question):
            continue
        shown = visible_codes(question, evaluation.values)
        open_.append(
            OpenQuestion(
                key=question.key,
                section=question.section,
                question=title(question, person),
                kind=question.kind,
                choices=tuple(
                    (c.code, fill(c.label, person)) for c in question.choices if c.code in shown
                ),
                write_in_choice=question.write_in_choice,
                optional=question.optional,
                sensitive=question.sensitive,
                when_asked=when_asked(question, evaluation.base),
            )
        )
    return open_


def _routing(evaluation: Evaluation, person: Basics) -> Routing:
    body_section = BANK.section(BANK.question(BANK.body.question).section)
    return Routing(
        follow_up_path=evaluation.path,
        body_route=evaluation.values.get("body_route", "general"),
        organs=tuple(evaluation.values.get("body", ())),
        body_from_your_body=any(
            code not in BANK.body.not_given
            for code in (evaluation.answers.get(BANK.body.question) or {}).get("value") or []
        ),
        opening_line=_section_intro(body_section, person, evaluation),
    )


def oracle_view(db: Session, profile: Profile, account: User) -> OracleView:
    """What the Oracle gets about the health profile with every reply, from one read: the
    answered questions that apply, the open ones it may ask in conversation, and the routing
    (follow-up path, body route, and Path B's opening line). Health data: never logged."""
    rows = _answers(db, profile)
    person = basics(profile, account)
    evaluation = evaluate(person, _stored(rows))
    return OracleView(
        known=_known(evaluation, rows, person),
        open=_open(evaluation, person),
        routing=_routing(evaluation, person),
    )


# Details saved from conversations (stories 3.1, 3.3 and 6.1, 6 Nov 19:22: saved straight away)


def _with_saved(question: Question, stored: dict, saved: dict | None) -> dict:
    """What a detail from a conversation saves. Lists add to what's saved, so a reply naming one
    new medicine or symptom never drops the others (3.1: the Oracle "saves the symptoms or
    medicines"; taking something off is the client's, in My Health):

    - named_list (medicines, supplements, allergies): new names are added after the saved ones;
      a name already there (any case) keeps its saved entry;
    - checklist (symptoms): the ticked items are added; one ticked now is no longer N/A.

    Every other kind replaces the saved answer, as the client's own edit would."""
    if saved is None:
        return stored
    if question.kind == "named_list":
        items = list(saved.get("value") or [])
        names = {item["name"].casefold() for item in items}
        for item in stored["value"]:
            if item["name"].casefold() not in names:
                names.add(item["name"].casefold())
                items.append(item)
        return {"value": items}
    if question.kind == "checklist":
        before = saved.get("value") or {}
        selected = set(before.get("selected", [])) | set(stored["value"]["selected"])
        not_applicable = (
            set(before.get("not_applicable", [])) | set(stored["value"]["not_applicable"])
        ) - selected
        return {
            "value": {
                "selected": [code for code in question.codes if code in selected],
                "not_applicable": [code for code in question.codes if code in not_applicable],
            }
        }
    return stored


def save_from_conversation(
    db: Session,
    profile: Profile,
    account: User,
    question_key: str,
    value: Any,
    other: str | None,
    conversation_id: Any,
) -> HealthAnswer | None:
    """Saves something the Oracle learned in a conversation as the profile's answer, marked as
    added from that conversation (6.1: "Added from our conversation on [date]"). The client can
    change or remove it in My Health. Saved during the free trial too (3.3).

    Returns None, saving nothing, when it doesn't fit: an unknown question, a value the question
    doesn't take (the Oracle's output is untrusted, so it's checked like the app's), a question
    that doesn't apply to the profile, a list that would grow past its limit, or no change.

    The caller holds the profile row lock (profile first, then the conversation, as when sending
    a message), calls `record_conversation_saves` once for the reply, and commits."""
    question = BANK.question(question_key)
    if question is None:
        return None
    person = basics(profile, account)
    try:
        stored = normalize(question, value, other, person)
    except AnswerProblem:
        return None
    if stored is None:
        return None
    rows = _answers(db, profile)
    row = rows.get(question_key)
    stored = _with_saved(question, stored, row.answer if row is not None else None)
    if question.kind == "named_list" and len(stored["value"]) > settings.health_list_max_items:
        return None
    if row is not None and row.answer == stored:
        return None
    before = _stored(rows)
    if not evaluate(person, before).applies(question_key):
        return None
    after = evaluate(person, {**before, question_key: stored})
    if not after.applies(question_key) or hidden_choice(question, stored, after.values):
        return None
    if row is None:
        row = HealthAnswer(profile_id=profile.id, question_key=question_key)
        db.add(row)
    row.answer = stored
    row.source = "conversation"
    row.conversation_id = conversation_id
    row.updated_at = datetime.now(UTC)  # the date "Added from our conversation on [date]" shows
    db.flush()
    return row


def record_conversation_saves(db: Session, profile: Profile, account: User, saved: int) -> None:
    """Story 6.1's log of the change, with its date and that it came from a conversation, plus
    the review reminders and the Wellness Plan update. Once per reply that saved anything."""
    if saved:
        _record_update(db, profile, account, None, "conversation", saved, 0)


@dataclass(frozen=True)
class AddedDetail:
    """A detail the Oracle added to the health profile from a conversation (story 3.3's list
    below the summary). Health data."""

    key: str  # the question's code (app/health/questions.json)
    section: str
    question: str  # worded for the profile
    answer: str  # the saved answer in words
    added_at: datetime  # "Added from our conversation on [date]" (6.1)


def added_from_conversation(
    db: Session,
    profile: Profile,
    account: User,
    conversation_id: Any,
    since: datetime | None = None,
) -> list[AddedDetail]:
    """Story 3.3: what the Oracle has added to the health profile from this conversation, in the
    bank's order, for "Here’s what I’ve added to your health profile from our conversation. If
    anything isn’t right, you can change or remove it in My Health." with Review in My Health.
    Empty when nothing was added: the list isn't shown. `since` keeps only what was added after
    then (for example since the summary was last shared).

    Only answers still as the Oracle saved them: one the client has since changed in My Health
    is theirs, and one they removed is gone. Answers to questions that no longer apply aren't
    listed, as in My Health. Read-only; works during the free trial too."""
    rows = _answers(db, profile)
    person = basics(profile, account)
    evaluation = evaluate(person, _stored(rows))
    added = []
    for question in evaluation.questions:
        row = rows.get(question.key)
        if row is None or row.source != "conversation" or row.conversation_id != conversation_id:
            continue
        if since is not None and row.updated_at < since:
            continue
        added.append(
            AddedDetail(
                key=question.key,
                section=question.section,
                question=title(question, person),
                answer=describe(question, row.answer, person),
                added_at=row.updated_at,
            )
        )
    return added


# Changes a logged visit suggests (story 5.2: "the Oracle asks the Client before updating their
# health profile"), saved as pending facts the client confirms or discards


def propose_fact(
    db: Session,
    profile: Profile,
    account: User,
    question_key: str,
    value: Any,
    other: str | None = None,
    conversation_id: Any = None,
) -> HealthFact | None:
    """Saves a change a logged visit suggests (5.2) as a pending fact, replacing any pending one
    for the same question. Returns None, saving nothing, when it doesn't fit: an unknown question, a
    value the question doesn't take, a question that doesn't apply to the profile, or the
    answer that's already saved. Doesn't commit: the caller does, with its own changes."""
    question = BANK.question(question_key)
    if question is None:
        return None
    person = basics(profile, account)
    try:
        stored = normalize(question, value, other, person)
    except AnswerProblem:
        return None
    rows = _answers(db, profile)
    if stored is None:
        return None
    evaluation = evaluate(person, _stored(rows))
    if not evaluation.applies(question_key) or hidden_choice(question, stored, evaluation.values):
        return None
    if question_key in rows and rows[question_key].answer == stored:
        return None
    statement = (
        insert(HealthFact)
        .values(
            profile_id=profile.id,
            question_key=question_key,
            answer=stored,
            conversation_id=conversation_id,
            status="pending",
        )
        .on_conflict_do_update(
            index_elements=[HealthFact.profile_id, HealthFact.question_key],
            # Rendered as written, so Postgres matches it to the partial unique index.
            index_where=text("status = 'pending'"),
            set_={
                "answer": stored,
                "conversation_id": conversation_id,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(HealthFact.id)
    )
    fact_id = db.scalar(statement)
    return db.get(HealthFact, fact_id, populate_existing=True)


def _fact_out(
    fact: HealthFact,
    question: Question,
    person: Basics,
    rows: dict[str, HealthAnswer],
    evaluation: Evaluation,
) -> HealthFactOut:
    answer = fact.answer or {}  # none once discarded
    return HealthFactOut(
        id=fact.id,
        profile_id=fact.profile_id,
        question=question_out(question, person, rows.get(question.key), evaluation),
        value=answer.get("value"),
        other=answer.get("other"),
        conversation_id=fact.conversation_id,
        status=fact.status,
        created_at=fact.created_at,
    )


def _fact_result(
    db: Session, profile: Profile, account: User, fact: HealthFact, question: Question
) -> HealthFactOut:
    """One fact, with its question and the saved answer as they are now."""
    person = basics(profile, account)
    rows = _answers(db, profile)
    return _fact_out(fact, question, person, rows, evaluate(person, _stored(rows)))


def list_facts(
    db: Session, profile: Profile, account: User, conversation_id: Any = None
) -> list[HealthFactOut]:
    """The profile's pending facts, oldest first; optionally only one conversation's. A fact
    whose question was taken out of the bank isn't listed."""
    query = select(HealthFact).where(
        HealthFact.profile_id == profile.id, HealthFact.status == "pending"
    )
    if conversation_id is not None:
        query = query.where(HealthFact.conversation_id == conversation_id)
    person = basics(profile, account)
    rows = _answers(db, profile)
    evaluation = evaluate(person, _stored(rows))
    facts = []
    for fact in db.scalars(query.order_by(HealthFact.created_at)):
        question = BANK.question(fact.question_key)
        if question is not None:
            facts.append(_fact_out(fact, question, person, rows, evaluation))
    return facts


def _owned_fact(db: Session, profile: Profile, fact_id: Any) -> HealthFact:
    """The fact, locked, if it's this profile's. Any other gets the same 404."""
    fact = db.scalars(
        select(HealthFact)
        .where(HealthFact.id == fact_id, HealthFact.profile_id == profile.id)
        .with_for_update()
    ).first()
    if fact is None:
        raise AppError(404, "health_fact_not_found", FACT_NOT_FOUND)
    return fact


def _fact_question(fact: HealthFact) -> Question:
    question = BANK.question(fact.question_key)
    if question is None:
        raise AppError(409, "not_applicable", NOT_APPLICABLE)
    return question


def _normalized(question: Question, sent: AnswerIn, person: Basics) -> dict:
    try:
        stored = normalize(question, sent.value, sent.other, person)
    except AnswerProblem as problem:
        raise AppError(422, problem.code, problem.message, "value") from None
    if stored is None:
        raise AppError(422, "invalid_answer", "Please check this answer and try again.", "value")
    return stored


def edit_fact(
    db: Session, profile: Profile, account: User, fact_id: Any, sent: AnswerIn
) -> HealthFactOut:
    """Changes a pending fact's value before it's confirmed."""
    with _saving(db):
        fact = _owned_fact(db, profile, fact_id)
        if fact.status == "confirmed":
            raise AppError(409, "health_fact_saved", FACT_ALREADY_SAVED)
        if fact.status == "discarded":
            raise AppError(409, "health_fact_discarded", FACT_ALREADY_DISCARDED)
        question = _fact_question(fact)
        person = basics(profile, account)
        fact.answer = _normalized(question, sent, person)
        db.commit()
    return _fact_result(db, profile, account, fact, question)


def confirm_fact(
    db: Session,
    profile: Profile,
    account: User,
    fact_id: Any,
    sent: AnswerIn | None,
    request: Request,
) -> HealthFactConfirmed:
    """Saves the fact (or the edited value sent with it) as the answer, marked as coming from
    its conversation. Confirming again changes nothing."""
    with _saving(db):
        db.refresh(profile, with_for_update=True)  # the same order as save_health_profile
        check_can_use(profile)
        fact = _owned_fact(db, profile, fact_id)
        question = _fact_question(fact)
        person = basics(profile, account)
        rows = _answers(db, profile)
        before = evaluate(person, _stored(rows)).completion
        if fact.status == "confirmed":
            return HealthFactConfirmed(
                fact=_fact_result(db, profile, account, fact, question),
                message=CHANGES_SAVED,
                celebration=None,
                completion=before,
            )
        if fact.status == "discarded":
            raise AppError(409, "health_fact_discarded", FACT_ALREADY_DISCARDED)
        if sent is not None:
            stored = _normalized(question, sent, person)
        else:  # checked again: the rules or the profile may have changed since
            stored = _normalized(
                question,
                AnswerIn(value=fact.answer.get("value"), other=fact.answer.get("other")),
                person,
            )
        merged = {**_stored(rows), question.key: stored}
        evaluation = evaluate(person, merged)
        if not evaluation.applies(question.key):
            raise AppError(409, "not_applicable", NOT_APPLICABLE)
        if hidden_choice(question, stored, evaluation.values):
            raise AppError(422, "invalid_choice", CHOOSE_AN_OPTION, "value")

        row = rows.get(question.key)
        if row is None:
            row = HealthAnswer(profile_id=profile.id, question_key=question.key)
            db.add(row)
        row.answer = stored
        # A fact from a visit review (5.2) has no conversation: the client confirmed it, so it
        # doesn't show "Added from our conversation on [date]".
        row.source = "conversation" if fact.conversation_id is not None else "client"
        row.conversation_id = fact.conversation_id
        fact.answer = stored
        fact.status = "confirmed"
        fact.resolved_at = datetime.now(UTC)
        _record_update(db, profile, account, request, row.source, 1, 0)
        db.commit()

    after = evaluation.completion
    return HealthFactConfirmed(
        fact=_fact_result(db, profile, account, fact, question),
        message=CHANGES_SAVED,
        celebration=PROFILE_COMPLETE if after == 100 and before < 100 else None,
        completion=after,
    )


def discard_fact(db: Session, profile: Profile, account: User, fact_id: Any) -> HealthFactOut:
    """The client doesn't want it saved: the value is cleared. Discarding again changes
    nothing; a saved one is changed or removed in My Health instead."""
    with _saving(db):
        fact = _owned_fact(db, profile, fact_id)
        question = _fact_question(fact)
        if fact.status == "confirmed":
            raise AppError(409, "health_fact_saved", FACT_ALREADY_SAVED)
        if fact.status == "pending":
            fact.status = "discarded"
            fact.answer = None
            fact.resolved_at = datetime.now(UTC)
        db.commit()
    return _fact_result(db, profile, account, fact, question)
