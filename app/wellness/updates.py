"""Creating and updating the Wellness Plan (story 7.1): the `wellness.update_plan` job.

Each job is one new item for one profile (app/wellness/triggers.py): a full guidance summary, a
logged or edited visit, or a health profile change. The job:

1. checks the plan may change: a subscription (no plan during the trial), a usable profile, and
   the item still there (a deleted visit log or conversation is skipped). Only a guidance
   summary creates a plan; the rest update one that exists;
2. asks the Oracle's `wellness_plan` call with the plan as it is and only the new item, with no
   transaction or lock held;
3. cleans the answer (the age rules: no products, product or cleanse links, or Foundational
   Nutraceuticals below the age of majority), then saves it under the plan's row lock as a new
   version, unless another update got there first, when it asks again with the new plan;
4. records the version, schedules the check-ins, and tells the client (12.1).

A failure marks the plan ("I couldn’t update your Wellness Plan just now. I’ll try again
shortly.") and raises, so the worker tries again. Oracle failures are logged by class name.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, get_args

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.conversations.models import Conversation
from app.conversations.widgets import prepare_widget
from app.core import audit
from app.core.ages import is_adult, today
from app.core.errors import AppError
from app.core.schemas import clean_line, clean_message
from app.guidance.models import GuidanceSummary
from app.notifications import service as notifications
from app.oracle import contract
from app.oracle.contract import PRODUCT_LINK, Oracle, OracleError
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.visits import service as visits
from app.visits.models import VisitLog
from app.wellness import protocols, service
from app.wellness.context import oracle_context
from app.wellness.models import WellnessPlan, WellnessPlanItem
from app.wellness.triggers import plan_allowed

logger = logging.getLogger(__name__)

# Asking again when another update saved first; past that the job fails and is retried.
UPDATE_ATTEMPTS = 3
# Caps on what's kept from the Oracle, so one bad answer can't fill the plan.
TEXT_MAX_LENGTH = 4000
LINE_MAX_LENGTH = 500
ITEMS_MAX = 30
FOLLOW_UP_MAX_DAYS = 365
NOTICE_CODES = frozenset(get_args(contract.PlanNotice))
PILLAR_CODES = frozenset(get_args(contract.PillarCode))
RECOMMENDATION_KINDS = frozenset(get_args(contract.RecommendationKind))
SOURCE_TYPES = {
    "guidance_summary": "guidance_summary",
    "visit_logged": "visit_log",
    "visit_edited": "visit_log",
    "health_profile": "health_profile",
}


class PlanUpdateFailed(Exception):
    """The update couldn't be made this time; the worker tries again. No details: they could
    be health data."""


@dataclass
class _Prepared:
    plan_id: uuid.UUID
    version: int
    profile: Profile
    account: User
    adult: bool
    trigger: str
    source_id: uuid.UUID | None
    context: contract.ProfileContext
    request: contract.PlanRequest


@dataclass
class _Cleaned:
    clinical_summary: str | None = None
    immediate_dietary_action: str | None = None
    focus_areas: list[dict[str, Any]] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    pillars: dict[str, dict[str, Any]] = field(default_factory=dict)
    products: list[dict[str, Any]] | None = None
    notices: list[str] | None = None
    conflicts: list[str] | None = None


# The new item, as the Oracle gets it


def _summary_item(content: dict[str, Any]) -> contract.GuidanceSummary:
    """A stored guidance summary (app/guidance) as the contract's dataclass."""
    return contract.GuidanceSummary(
        stage=content["stage"],
        what_im_hearing=content["what_im_hearing"],
        what_this_may_mean=content["what_this_may_mean"],
        word_from_the_oracle=content["word_from_the_oracle"],
        hypothalamic_connection=content.get("hypothalamic_connection"),
        questions_for_provider=list(content.get("questions_for_provider") or []),
        tests_worth_discussing=[
            contract.TestToDiscuss(
                name=test["name"], why=test.get("why") or "", url=test.get("url")
            )
            for test in content.get("tests_worth_discussing") or []
        ],
        what_you_can_do_now=[
            contract.ActionStep(text=step["text"], protocol=step.get("protocol"))
            for step in content.get("what_you_can_do_now") or []
        ],
        recommendations=[
            contract.Recommendation(
                label=item["label"],
                url=item["url"],
                kind=item["kind"],
                why=item.get("why"),
                label_directions=item.get("label_directions"),
            )
            for item in content.get("recommendations") or []
        ],
        recommended_next_steps=list(content.get("recommended_next_steps") or []),
        provider_visit_relevant=bool(content.get("provider_visit_relevant")),
    )


def _source(
    db: Session, profile: Profile, trigger: str, source_id: uuid.UUID | None, payload: dict
) -> tuple[bool, contract.GuidanceSummary | None, contract.LoggedVisit | None]:
    """(still there, summary, visit) for the job's item."""
    adult = is_adult(profile.date_of_birth)
    if trigger == "guidance_summary":
        summary = db.get(GuidanceSummary, source_id) if source_id else None
        if summary is None or summary.content is None or summary.profile_id != profile.id:
            return False, None, None
        conversation = db.get(Conversation, summary.conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            return False, None, None
        return True, _summary_item(summary.content), None
    if trigger in ("visit_logged", "visit_edited"):
        log = db.get(VisitLog, source_id) if source_id else None
        if log is None or log.profile_id != profile.id or log.revision != payload.get("revision"):
            return False, None, None  # deleted, or saved again (that save has its own job)
        return True, None, visits.logged_visit(log, adult=adult)
    return trigger == "health_profile", None, None


def _prepare(db: Session, payload: dict[str, Any]) -> _Prepared | None:
    profile = db.get(Profile, uuid.UUID(payload["profile_id"]))
    if profile is None:
        return None
    account = db.get(User, profile.account_id)
    if account is None or not plan_allowed(account):
        return None  # 7.1: no plan is created or updated during the free trial
    try:
        check_can_use(profile)
    except AppError:
        return None  # turned off, being deleted, or not set up
    trigger = payload["trigger"]
    source_id = uuid.UUID(payload["source_id"]) if payload.get("source_id") else None
    exists, summary, visit = _source(db, profile, trigger, source_id, payload)
    if not exists:
        return None
    plan = service.plan_row(db, profile)
    if plan is None or plan.version == 0:
        if trigger != "guidance_summary":
            return None  # 7.1: the plan starts with the profile's first guidance summary
        if plan is None:
            db.execute(
                insert(WellnessPlan)
                .values(id=uuid.uuid4(), profile_id=profile.id, version=0)
                .on_conflict_do_nothing(index_elements=["profile_id"])
            )
            plan = service.plan_row(db, profile)
    current = service.current_plan(db, plan) if plan.version > 0 else None
    return _Prepared(
        plan_id=plan.id,
        version=plan.version,
        profile=profile,
        account=account,
        adult=is_adult(profile.date_of_birth),
        trigger=trigger,
        source_id=source_id,
        context=oracle_context(db, profile, account),
        request=contract.PlanRequest(
            trigger=trigger, current=current, summary=summary, visit=visit
        ),
    )


# Cleaning what the Oracle returned. Anything of the wrong shape is dropped.


def _text(value: object) -> str | None:
    return clean_message(value)[:TEXT_MAX_LENGTH] or None if isinstance(value, str) else None


def _line(value: object) -> str | None:
    return clean_line(value)[:LINE_MAX_LENGTH] or None if isinstance(value, str) else None


def _lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [line for value in values[:ITEMS_MAX] if (line := _line(value))]


def _items(values: object, kind: type) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [value for value in values[:ITEMS_MAX] if isinstance(value, kind)]


def _days(value: object) -> date | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= FOLLOW_UP_MAX_DAYS:
        return None
    return today() + timedelta(days=value)


def _product(item: object, adult: bool) -> dict[str, Any] | None:
    """A product link: adults only, with a label and an https URL (the 3.1 rules). No price
    can be stored: the contract has none."""
    if not adult or not isinstance(item, contract.Recommendation):
        return None
    link = prepare_widget({"kind": PRODUCT_LINK, "label": item.label, "url": item.url}, adult=True)
    if link is None:
        return None
    kind = item.kind if item.kind in RECOMMENDATION_KINDS else "other"
    return {
        "label": link["label"],
        "url": link["url"],
        "kind": kind,
        "why": _line(item.why),
        # Genesis products: the label's directions, word for word (7.1).
        "label_directions": _line(item.label_directions) if kind == "genesis_product" else None,
    }


def _focus_changes(result: contract.PlanUpdate, known: set[str]) -> list[dict[str, Any]]:
    changes = []
    for area in _items(result.focus_areas, contract.PlanFocusArea):
        if area.id is not None and area.id not in known:
            continue  # not one of this plan's focus areas
        change = {
            "id": area.id,
            "title": _line(area.title),
            "recommendations": _lines(area.recommendations),
            "time_frame": _line(area.time_frame),
            "follow_up_on": _days(area.follow_up_in_days),
            "remove": area.remove if area.remove in ("resolved", "course_finished") else None,
        }
        if area.id is None and (change["title"] is None or change["remove"]):
            continue  # a new one needs a title
        changes.append(change)
    return changes


def _todo_changes(
    result: contract.PlanUpdate, known: set[str], adult: bool
) -> list[dict[str, Any]]:
    changes = []
    for todo in _items(result.todos, contract.PlanTodo):
        if todo.id is not None and todo.id not in known:
            continue
        protocol = _line(todo.protocol)
        if protocol and not protocols.suitable(protocol, adult=adult):
            if protocols.known(protocol):
                continue  # 7.1: no product or cleanse for teens and children
            protocol = None  # not a library section
        if not adult and todo.product is not None:
            continue  # an item about a product: never for teens and children
        change = {
            "id": todo.id,
            "text": _line(todo.text),
            "protocol": protocol,
            "product": _product(todo.product, adult),
            "follow_up_on": _days(todo.due_in_days),
            "done": todo.done is True,
            "remove": todo.remove is True,
        }
        if todo.id is None and (change["text"] is None or change["remove"]):
            continue
        changes.append(change)
    return changes


def _pillar_changes(result: contract.PlanUpdate, adult: bool) -> dict[str, dict[str, Any]]:
    pillars = {}
    for pillar in _items(result.pillars, contract.PlanPillar):
        if pillar.code not in PILLAR_CODES:
            continue
        if pillar.code in protocols.ADULT_ONLY_PILLARS and not adult:
            continue  # 7.1: no Foundational Nutraceuticals pillar for teens and children
        healthy_four = None
        if pillar.code == "diet" and isinstance(pillar.healthy_four, list):
            healthy_four = [
                {"name": name, "target": target}
                for item in _items(pillar.healthy_four, contract.HealthyFourTarget)
                if (name := _line(item.name)) and (target := _line(item.target))
            ] or None
        pillars[pillar.code] = {
            "adjustment": _text(pillar.adjustment),
            "sacred_seven": adult
            and pillar.code == "nutraceuticals"
            and pillar.sacred_seven is True,
            "healthy_four": healthy_four,
            "insulin_resistance_phase": (
                _line(pillar.insulin_resistance_phase) if pillar.code == "diet" else None
            ),
        }
    return pillars


def _clean(
    result: object, prepared: _Prepared, plan_items: list[WellnessPlanItem]
) -> _Cleaned | None:
    """The changes to save, or None when there's nothing to change."""
    if not isinstance(result, contract.PlanUpdate):
        raise OracleError("The plan update isn't a PlanUpdate.")
    if not result.changed:
        return None
    adult = prepared.adult
    creating = prepared.request.current is None
    focus_ids = {str(item.id) for item in plan_items if item.kind == "focus_area"}
    todo_ids = {str(item.id) for item in plan_items if item.kind == "todo"}
    cleaned = _Cleaned(
        clinical_summary=_text(result.clinical_summary),
        immediate_dietary_action=_text(result.immediate_dietary_action),
        focus_areas=_focus_changes(result, focus_ids),
        todos=_todo_changes(result, todo_ids, adult),
        pillars=_pillar_changes(result, adult),
    )
    if creating and cleaned.clinical_summary is None:
        raise OracleError("A new plan needs its clinical summary.")
    if result.products is not None:
        products = [
            _product(item, adult) for item in _items(result.products, contract.Recommendation)
        ]
        cleaned.products = [item for item in products if item]
    if result.notices is not None:
        cleaned.notices = [
            code
            for code in dict.fromkeys(_items(result.notices, str))
            if code in NOTICE_CODES and (adult or code not in service.ADULT_NOTICES)
        ]
    if result.conflicts is not None:
        cleaned.conflicts = [
            i for i in dict.fromkeys(_items(result.conflicts, str)) if i in todo_ids
        ]
    return cleaned


# Saving


def _apply(db: Session, prepared: _Prepared, cleaned: _Cleaned | None) -> bool:
    """Saves the update as the plan's next version. False when another update saved first:
    the Oracle's answer was for an older plan, so it's asked again. Doesn't commit."""
    plan = db.scalar(
        select(WellnessPlan).where(WellnessPlan.id == prepared.plan_id).with_for_update()
    )
    if plan is None:
        return True  # the profile was deleted
    if plan.version != prepared.version:
        return False
    if cleaned is None:
        plan.update_failed_at = None
        return True
    profile, account = prepared.profile, prepared.account
    now = datetime.now(UTC)
    creating = plan.version == 0
    items = {str(item.id): item for item in service.active_items(db, plan, lock=True)}
    changes: dict[str, list[str]] = {
        "added": [],
        "updated": [],
        "completed": [],
        "removed": [],
        "fields": [],
    }
    touched: list[WellnessPlanItem] = []
    resolved = False

    content = dict(plan.content or {"pillars": {}, "products": [], "notices": [], "conflicts": []})
    for key in ("clinical_summary", "immediate_dietary_action"):
        value = getattr(cleaned, key)
        if value is not None and value != content.get(key):
            content[key] = value
            changes["fields"].append(key)
    if cleaned.pillars:
        content["pillars"] = {**(content.get("pillars") or {}), **cleaned.pillars}
        changes["fields"].append("pillars")
    for key in ("products", "notices", "conflicts"):
        value = getattr(cleaned, key)
        if value is not None and value != content.get(key):
            content[key] = value
            changes["fields"].append(key)

    position = (
        db.scalar(
            select(func.max(WellnessPlanItem.position)).where(WellnessPlanItem.plan_id == plan.id)
        )
        or 0
    )
    source_type = SOURCE_TYPES[prepared.trigger]

    def add(kind: str, title: str, details: dict[str, Any], follow_up_on: date | None) -> None:
        nonlocal position
        position += 1
        item = WellnessPlanItem(
            id=uuid.uuid4(),
            plan_id=plan.id,
            kind=kind,
            title=title,
            details=details,
            position=position,
            status="open",
            follow_up_on=follow_up_on,
            source_type=source_type,
            source_id=prepared.source_id,
        )
        db.add(item)
        touched.append(item)
        changes["added"].append(str(item.id))

    for change in cleaned.focus_areas:
        if change["id"] is None:
            add(
                "focus_area",
                change["title"],
                {"recommendations": change["recommendations"], "time_frame": change["time_frame"]},
                change["follow_up_on"],
            )
            continue
        item = items.get(change["id"])
        if item is None:
            continue  # gone since the Oracle was asked
        if change["remove"]:
            item.removed_at, item.removed_reason = now, change["remove"]
            resolved = resolved or change["remove"] == "resolved"
            changes["removed"].append(change["id"])
        else:
            item.title = change["title"] or item.title
            details = dict(item.details)
            if change["recommendations"]:
                details["recommendations"] = change["recommendations"]
            if change["time_frame"]:
                details["time_frame"] = change["time_frame"]
            item.details = details
            if change["follow_up_on"]:
                item.follow_up_on = change["follow_up_on"]
            changes["updated"].append(change["id"])
        touched.append(item)

    for change in cleaned.todos:
        if change["id"] is None:
            add(
                "todo",
                change["text"],
                {"protocol": change["protocol"], "product": change["product"]},
                change["follow_up_on"],
            )
            continue
        item = items.get(change["id"])
        if item is None:
            continue  # gone since the Oracle was asked
        if change["remove"]:
            item.removed_at, item.removed_reason = now, "removed"
            changes["removed"].append(change["id"])
        else:
            item.title = change["text"] or item.title
            details = dict(item.details)
            if change["protocol"]:
                details["protocol"] = change["protocol"]
            if change["product"]:
                details["product"] = change["product"]
            item.details = details
            if change["follow_up_on"]:
                item.follow_up_on = change["follow_up_on"]
            if change["done"] and item.status != "done":
                # 7.1: confirmed done (a visit, a check-in): the Oracle won't ask again.
                item.status, item.completed_at, item.completed_by = "done", now, "oracle"
                changes["completed"].append(change["id"])
            else:
                changes["updated"].append(change["id"])
        touched.append(item)

    if not creating and not any(changes.values()):
        plan.update_failed_at = None
        return True  # nothing actually changed

    removed = set(changes["removed"])
    if removed and content.get("conflicts"):
        content["conflicts"] = [i for i in content["conflicts"] if i not in removed]
    plan.content = content
    plan.version += 1
    plan.content_updated_at = now
    plan.update_failed_at = None
    for item in touched:
        service.schedule_check_in(db, account, profile, item)
    outcome = "created" if creating else "resolved" if resolved else "updated"
    service.record_version(
        db,
        plan,
        trigger=prepared.trigger,
        source_id=prepared.source_id,
        outcome=outcome,
        changes=changes,
    )
    details: dict[str, Any] = {"version": plan.version, "trigger": prepared.trigger}
    if prepared.source_id is not None:
        details["source_id"] = str(prepared.source_id)
    audit.record(
        db,
        "wellness_plan.created" if creating else "wellness_plan.updated",
        target_type="wellness_plan",
        target_id=plan.id,
        details=details,
    )
    if not creating:
        # 7.1 and 12.1: "Your Wellness Plan has been updated."
        notifications.notify(db, account, service.UPDATED, profile=profile)
    return True


def _mark_failed(db: Session, plan_id: uuid.UUID) -> None:
    db.rollback()
    db.execute(
        update(WellnessPlan)
        .where(WellnessPlan.id == plan_id)
        .values(update_failed_at=datetime.now(UTC))
    )
    db.commit()


def run_update(db: Session, payload: dict[str, Any], oracle: Oracle) -> None:
    """The wellness.update_plan job. The worker commits."""
    for _ in range(UPDATE_ATTEMPTS):
        prepared = _prepare(db, payload)
        if prepared is None:
            return
        plan = db.get(WellnessPlan, prepared.plan_id)
        plan_items = service.active_items(db, plan)
        db.commit()  # nothing is held while the Oracle works
        try:
            result = oracle.wellness_plan(prepared.context, prepared.request)
            cleaned = _clean(result, prepared, plan_items)
        except Exception as error:  # the AI service failed, or answered something unusable
            logger.warning(
                "Wellness Plan update failed: %s (profile %s)",
                type(error).__name__,
                prepared.profile.id,
            )
            _mark_failed(db, prepared.plan_id)
            raise PlanUpdateFailed from None
        if _apply(db, prepared, cleaned):
            return
        db.rollback()
    raise PlanUpdateFailed
