"""Viewing and using the Wellness Plan (story 7.1), and the Wellness Protocols library.

The plan is created and updated by the system only (app/wellness/updates.py, from the triggers
in app/wellness/triggers.py); the client views it, ticks To Do items and opens the library.
It's greyed out during the free trial, and not shown after a subscription ends (11.3).

The plan is health data: never logged, and its audit events hold ids only. Teens and children
see it as education only: whatever is stored, no products, product or cleanse links, or
Foundational Nutraceuticals pillar is shown below the age of majority.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core import audit
from app.core.ages import is_adult, today
from app.core.config import settings
from app.core.errors import AppError
from app.core.schemas import clean_line
from app.notifications import service as notifications
from app.oracle import contract
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.wellness import protocols
from app.wellness.models import WellnessPlan, WellnessPlanItem, WellnessPlanVersion
from app.wellness.schemas import (
    FocusAreaOut,
    HealthyFourOut,
    ItemTicked,
    LibraryOut,
    LibrarySectionOut,
    LibraryTabOut,
    LinkOut,
    NoticeOut,
    PillarOut,
    PlanCardOut,
    PlanCardScreen,
    ProductOut,
    ProgressOut,
    TodoOut,
    WellnessPlanOut,
    WellnessPlanScreen,
)
from app.wellness.triggers import plan_allowed

CHECK_IN = "wellness_plan_check_in"  # the notifications kind (story 12.1)
UPDATED = "wellness_plan_updated"

# Story 7.1's messages.
PLAN_CREATED = (
    "I’ve started your Wellness Plan. It’s where we’ll keep track of everything we’re working on "
    "together."
)
PLAN_UPDATED = "Your Wellness Plan has been updated."
FOCUS_REMOVED = (
    "Your Wellness Plan has been updated, because you’ve confirmed you’re no longer having these "
    "issues."
)
NO_PLAN_YET = (
    "Your Wellness Plan will appear here after our first conversation. Tell me how you’re "
    "feeling, and we’ll get started."
)
MEASUREMENTS_NEEDED = "Share your measurements with me, and I’ll work out your personal targets."
ALL_DONE = "You’ve completed everything on your list. Well done!"
CONFLICT = (
    "Your new prescription may not go well with item {number} in your plan. Please mention it to "
    "your provider or pharmacist."
)
PLAN_LOCKED = "Subscribe to get your personal Wellness Plan."
ITEM_UPDATE_FAILED = "We couldn’t update this item just now. Please try again."
PLAN_UPDATE_FAILED = "I couldn’t update your Wellness Plan just now. I’ll try again shortly."
PLAN_LOAD_FAILED = "We couldn’t load your Wellness Plan. Please try again."
NOTICES: dict[str, str] = {
    "hyperthyroid_sacred_seven_first": (
        "Because of your thyroid, it’s best to start with Sacred Seven® on its own and check with "
        "your provider before adding Genesis Gold®."
    ),
    "gen_pro_dose": (
        "How to take it (from the label): 2 pumps, twice daily. Here’s the Gen-Pro® protocol, too."
    ),
    "gender_affirming_hormones": (
        "Talk with the provider who manages your hormones before adding progesterone or other "
        "hormone products."
    ),
    "cleanse_not_suitable": (
        "A cleanse isn’t the right fit for you right now. Let’s focus on other ways to support "
        "your body."
    ),
}
# About products: shown to adults only.
ADULT_NOTICES = frozenset({"hyperthyroid_sacred_seven_first", "gen_pro_dose"})
# The library section a notice mentions.
NOTICE_LINKS = {"gen_pro_dose": protocols.GEN_PRO}
# Not in the stories (docs/decisions/phase-6-7-visits-wellness.md).
ITEM_NOT_FOUND = "We couldn’t find that item in the Wellness Plan."
ASK_FOCUS = "Can you tell me more about “{title}” in {whose} Wellness Plan?"
ASK_TODO = "Can you explain why “{text}” is in {whose} Wellness Plan?"
DIETARY_ACTION = "Immediate dietary action"
LIBRARY_LOAD_FAILED = "We couldn’t load the Wellness Protocols. Please try again."


def check_unlocked(account: User) -> None:
    """7.1: during the free trial the plan is greyed out with "Subscribe to get your personal
    Wellness Plan." (11.3: nor is it shown after a subscription ends)."""
    if not plan_allowed(account):
        raise AppError(403, "upgrade_required", PLAN_LOCKED)


@contextmanager
def _failing_with(db: Session, code: str, message: str) -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, code, message) from None


def _adult(profile: Profile) -> bool:
    return (
        is_adult(profile.date_of_birth, profile.majority_state) if profile.date_of_birth else True
    )


def _first_name(profile: Profile, account: User) -> str:
    return clean_line((account.first_name if profile.is_self else profile.first_name) or "")


def plan_row(db: Session, profile: Profile, *, lock: bool = False) -> WellnessPlan | None:
    query = select(WellnessPlan).where(WellnessPlan.profile_id == profile.id)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def active_items(db: Session, plan: WellnessPlan, *, lock: bool = False) -> list[WellnessPlanItem]:
    """The items the plan shows: focus areas newest first, then To Do items in order."""
    query = select(WellnessPlanItem).where(
        WellnessPlanItem.plan_id == plan.id, WellnessPlanItem.removed_at.is_(None)
    )
    if lock:
        query = query.with_for_update()
    items = list(db.scalars(query))
    focus = sorted((i for i in items if i.kind == "focus_area"), key=lambda i: -i.position)
    todos = sorted((i for i in items if i.kind == "todo"), key=lambda i: i.position)
    return [*focus, *todos]


# Showing the plan


def _link(library: protocols.Library | None, key: str | None, adult: bool) -> LinkOut | None:
    """A library link, only while the protocol is published in the knowledge base (Super
    Admin 6.1) and suitable for the age. No library given: no links."""
    section = library.link(key, adult=adult) if library is not None else None
    if section is None:
        return None
    return LinkOut(tab=section.tab, section=section.key, title=section.title)


def product_out(data: dict[str, Any]) -> ProductOut:
    """A stored product link, with a Genesis product's label directions (7.1)."""
    return ProductOut(
        label=data["label"],
        url=data["url"],
        kind=data["kind"],
        why=data.get("why"),
        directions=(
            protocols.how_to_take(data.get("label_directions"))
            if data["kind"] == "genesis_product"
            else None
        ),
    )


def _product(data: dict[str, Any] | None, adult: bool) -> ProductOut | None:
    return product_out(data) if data and adult else None


def _whose(profile: Profile, account: User) -> str:
    return "my" if profile.is_self else f"{_first_name(profile, account)}’s"


def _todos(
    items: list[WellnessPlanItem],
    profile: Profile,
    account: User,
    adult: bool,
    library: protocols.Library | None = None,
) -> list[TodoOut]:
    todos = [item for item in items if item.kind == "todo"]
    return [
        TodoOut(
            id=item.id,
            number=number,
            text=item.title,
            done=item.status == "done",
            completed_at=item.completed_at,
            protocol=_link(library, item.details.get("protocol"), adult),
            product=_product(item.details.get("product"), adult),
            follow_up_on=item.follow_up_on,
            ask_prompt=ASK_TODO.format(text=item.title, whose=_whose(profile, account)),
        )
        for number, item in enumerate(todos, start=1)
    ]


def _progress(todos: list[TodoOut]) -> ProgressOut:
    dots = [todo.done for todo in todos]
    return ProgressOut(done=sum(dots), total=len(dots), dots=dots)


def _pillars(content: dict[str, Any], adult: bool, library: protocols.Library) -> list[PillarOut]:
    stored = content.get("pillars") or {}
    pillars = []
    for code, pillar_title, keys in protocols.PILLARS:
        if code in protocols.ADULT_ONLY_PILLARS and not adult:
            continue
        data = stored.get(code) or {}
        links = list(keys)
        if code == "nutraceuticals" and data.get("sacred_seven"):
            links.append(protocols.SACRED_SEVEN)
        healthy_four = data.get("healthy_four")
        pillars.append(
            PillarOut(
                code=code,
                title=pillar_title,
                adjustment=data.get("adjustment"),
                links=[link for key in links if (link := _link(library, key, adult))],
                healthy_four=(
                    [HealthyFourOut(**target) for target in healthy_four]
                    if code == "diet" and healthy_four
                    else None
                ),
                insulin_resistance_phase=(
                    data.get("insulin_resistance_phase") if code == "diet" else None
                ),
                message=MEASUREMENTS_NEEDED if code == "diet" and not healthy_four else None,
            )
        )
    return pillars


def _message(db: Session, plan: WellnessPlan) -> str | None:
    if plan.update_failed_at is not None:
        return PLAN_UPDATE_FAILED
    outcome = db.scalar(
        select(WellnessPlanVersion.outcome).where(
            WellnessPlanVersion.plan_id == plan.id, WellnessPlanVersion.version == plan.version
        )
    )
    return {"created": PLAN_CREATED, "resolved": FOCUS_REMOVED}.get(outcome, PLAN_UPDATED)


def plan_out(db: Session, plan: WellnessPlan, profile: Profile, account: User) -> WellnessPlanOut:
    adult = _adult(profile)
    content = plan.content
    library = protocols.load(db)
    items = active_items(db, plan)
    todos = _todos(items, profile, account, adult, library)
    progress = _progress(todos)
    numbers = {str(todo.id): todo.number for todo in todos}
    products = [product_out(item) for item in content.get("products") or []] if adult else []
    pillars = _pillars(content, adult, library)
    shows_products = adult and (
        bool(products)
        or any(todo.product for todo in todos)
        or any(p.code == "nutraceuticals" and p.adjustment for p in pillars)
    )
    whose = _whose(profile, account)
    return WellnessPlanOut(
        id=plan.id,
        profile_id=profile.id,
        title=f"{_first_name(profile, account)}’s Wellness Plan",
        last_updated=plan.content_updated_at,
        message=_message(db, plan),
        clinical_summary=content["clinical_summary"],
        immediate_dietary_action=content.get("immediate_dietary_action"),
        focus_areas=[
            FocusAreaOut(
                id=item.id,
                title=item.title,
                recommendations=item.details.get("recommendations") or [],
                time_frame=item.details.get("time_frame"),
                ask_prompt=ASK_FOCUS.format(title=item.title, whose=whose),
                added_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
            if item.kind == "focus_area"
        ],
        todos=todos,
        progress=progress,
        all_done=ALL_DONE if progress.total and progress.done == progress.total else None,
        pillars=pillars,
        products=products,
        notices=[
            NoticeOut(
                code=code, text=NOTICES[code], link=_link(library, NOTICE_LINKS.get(code), adult)
            )
            for code in content.get("notices") or []
            if code in NOTICES and (adult or code not in ADULT_NOTICES)
        ],
        alerts=[
            CONFLICT.format(number=numbers[item_id])
            for item_id in content.get("conflicts") or []
            if item_id in numbers
        ],
        product_disclaimer=protocols.FDA_DISCLAIMER if shows_products else None,
        disclosure=protocols.DISCLOSURE if shows_products else None,
    )


def get_plan(db: Session, profile: Profile, account: User) -> WellnessPlanScreen:
    """The active profile's plan (7.1), or the "No plan yet" message."""
    check_unlocked(account)
    with _failing_with(db, "load_failed", PLAN_LOAD_FAILED):
        plan = plan_row(db, profile)
        if plan is None or plan.version == 0:
            return WellnessPlanScreen(plan=None, message=NO_PLAN_YET)
        return WellnessPlanScreen(plan=plan_out(db, plan, profile, account), message=None)


def get_card(db: Session, profile: Profile, account: User) -> PlanCardScreen:
    """The Wellness Plan card (4.1, 6.1): the current focus, To Do progress with dots, and
    whether a check-in is due. Null when there's no plan yet: the card isn't shown."""
    check_unlocked(account)
    with _failing_with(db, "load_failed", PLAN_LOAD_FAILED):
        plan = plan_row(db, profile)
        if plan is None or plan.version == 0:
            return PlanCardScreen(card=None)
        items = active_items(db, plan)
        todos = _todos(items, profile, account, _adult(profile))
        focus = next((item.title for item in items if item.kind == "focus_area"), None)
        if focus is None and plan.content.get("immediate_dietary_action"):
            focus = DIETARY_ACTION
        due = today()
        return PlanCardScreen(
            card=PlanCardOut(
                profile_id=profile.id,
                title=f"{_first_name(profile, account)}’s Wellness Plan",
                current_focus=focus,
                progress=_progress(todos),
                check_in_due=any(
                    item.follow_up_on is not None
                    and item.follow_up_on <= due
                    and item.status == "open"
                    for item in items
                ),
                last_updated=plan.content_updated_at,
            )
        )


# Ticking To Do items


def schedule_check_in(db: Session, account: User, profile: Profile, item: WellnessPlanItem) -> None:
    """7.1's follow-up: a check-in on the day an item's time frame ends or it's due, through
    the notifications package, which skips it after an emergency or crisis (3.2), for a
    turned-off member, and when the client turned Wellness Plan notifications off. Replaces any
    waiting one; an item that's done, removed or has no date gets none."""
    notifications.cancel_scheduled(db, account, kind=CHECK_IN, target_id=item.id)
    if item.follow_up_on is None or item.removed_at is not None or item.status == "done":
        return
    run_at = datetime.combine(
        item.follow_up_on, time(settings.wellness_check_in_hour_utc), tzinfo=UTC
    )
    if run_at > datetime.now(UTC):
        notifications.schedule(db, account, CHECK_IN, run_at, profile=profile, target_id=item.id)


def tick_item(
    db: Session,
    profile: Profile,
    account: User,
    item_id: uuid.UUID,
    done: bool,
    request: Request,
) -> ItemTicked:
    """Ticks a To Do item, or unticks one done by mistake (7.1). The progress updates straight
    away, and the Oracle doesn't ask about a done item again (its check-in is cancelled)."""
    check_unlocked(account)
    check_can_use(profile)
    with _failing_with(db, "item_update_failed", ITEM_UPDATE_FAILED):
        plan = plan_row(db, profile)
        item = None
        if plan is not None and plan.version > 0:
            item = db.scalar(
                select(WellnessPlanItem)
                .where(
                    WellnessPlanItem.id == item_id,
                    WellnessPlanItem.plan_id == plan.id,
                    WellnessPlanItem.kind == "todo",
                    WellnessPlanItem.removed_at.is_(None),
                )
                .with_for_update()
            )
        if item is None:
            raise AppError(404, "plan_item_not_found", ITEM_NOT_FOUND)
        if (item.status == "done") != done:
            if done:
                item.status, item.completed_by = "done", "client"
                item.completed_at = datetime.now(UTC)
            else:
                item.status, item.completed_by, item.completed_at = "open", None, None
            schedule_check_in(db, account, profile, item)
            audit.record(
                db,
                "wellness_plan.item_completed" if done else "wellness_plan.item_reopened",
                actor_id=account.id,
                target_type="wellness_plan_item",
                target_id=item.id,
                request=request,
                details={"plan_id": str(plan.id)},
            )
        db.commit()
        todos = _todos(
            active_items(db, plan), profile, account, _adult(profile), protocols.load(db)
        )
    progress = _progress(todos)
    return ItemTicked(
        item=next(todo for todo in todos if todo.id == item.id),
        progress=progress,
        all_done=ALL_DONE if progress.total and progress.done == progress.total else None,
    )


# The library


def library(db: Session, profile: Profile) -> LibraryOut:
    """The Wellness Protocols library (7.1), for this profile's age, with each section's
    published knowledge base content (Super Admin 6.1: editing or archiving a protocol updates
    what clients see)."""
    adult = _adult(profile)
    with _failing_with(db, "load_failed", LIBRARY_LOAD_FAILED):
        published = protocols.load(db)
    return LibraryOut(
        tabs=[
            LibraryTabOut(
                key=tab.key,
                title=tab.title,
                product=tab.product,
                sections=[
                    LibrarySectionOut(
                        key=section.key,
                        title=section.title,
                        parts=list(section.parts),
                        content=published.content[section.key].text,
                        updated_at=published.content[section.key].published_at,
                        url=section.external_url,
                    )
                    for section in tab.sections
                ],
                fda_disclaimer=protocols.FDA_DISCLAIMER if tab.product else None,
                ownership_disclosure=protocols.DISCLOSURE if tab.product else None,
                shop_label=protocols.SHOP_LABEL if tab.shop_url else None,
                shop_url=tab.shop_url,
            )
            for tab in published.tabs_for(adult)
        ]
    )


# Versions


def _item_snapshot(item: WellnessPlanItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "title": item.title,
        "details": item.details,
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "follow_up_on": item.follow_up_on.isoformat() if item.follow_up_on else None,
        "source_type": item.source_type,
        "source_id": str(item.source_id) if item.source_id else None,
    }


def record_version(
    db: Session,
    plan: WellnessPlan,
    *,
    trigger: str,
    source_id: uuid.UUID | None,
    outcome: str,
    changes: dict[str, list[str]],
) -> None:
    """Saves plan.version as a new version row: the whole plan after the update, and what
    changed (7.1: every update is recorded, only the latest is shown). Call after the plan's
    and items' changes are made and plan.version is raised."""
    db.flush()
    db.add(
        WellnessPlanVersion(
            plan_id=plan.id,
            version=plan.version,
            trigger=trigger,
            source_id=source_id,
            outcome=outcome,
            snapshot={
                "content": plan.content,
                "items": [_item_snapshot(item) for item in active_items(db, plan)],
            },
            changes=changes,
        )
    )


# Deleting a visit log (story 5.2)


def _visit_items_query(plan: WellnessPlan, visit_log_id: uuid.UUID):
    return select(WellnessPlanItem).where(
        WellnessPlanItem.plan_id == plan.id,
        WellnessPlanItem.source_type == "visit_log",
        WellnessPlanItem.source_id == visit_log_id,
        WellnessPlanItem.removed_at.is_(None),
    )


def items_added_by_visit(db: Session, profile: Profile, visit_log_id: uuid.UUID) -> int:
    """5.2's "This visit added [X] items to your Wellness Plan": the ones still in the plan."""
    plan = plan_row(db, profile)
    if plan is None or plan.version == 0:
        return 0
    return len(db.scalars(_visit_items_query(plan, visit_log_id)).all())


def remove_items_added_by_visit(
    db: Session, account: User, profile: Profile, visit_log_id: uuid.UUID, request: Request
) -> int:
    """The client deleted a visit log and chose "remove them too": the items it added come off
    the plan, as a new version. Returns how many. Doesn't commit."""
    plan = plan_row(db, profile, lock=True)
    if plan is None or plan.version == 0:
        return 0
    items = list(db.scalars(_visit_items_query(plan, visit_log_id).with_for_update()))
    if not items:
        return 0
    now = datetime.now(UTC)
    for item in items:
        item.removed_at, item.removed_reason = now, "visit_deleted"
        notifications.cancel_scheduled(db, account, kind=CHECK_IN, target_id=item.id)
    content = dict(plan.content)
    removed = {str(item.id) for item in items}
    if content.get("conflicts"):
        content["conflicts"] = [i for i in content["conflicts"] if i not in removed]
        plan.content = content
    plan.version += 1
    plan.content_updated_at = now
    record_version(
        db,
        plan,
        trigger="visit_deleted",
        source_id=visit_log_id,
        outcome="updated",
        changes={"removed": sorted(removed)},
    )
    audit.record(
        db,
        "wellness_plan.updated",
        actor_id=account.id,
        target_type="wellness_plan",
        target_id=plan.id,
        request=request,
        details={"version": plan.version, "trigger": "visit_deleted"},
    )
    return len(items)


# For the Oracle


def _recommendation(data: dict[str, Any]) -> contract.Recommendation:
    return contract.Recommendation(
        label=data["label"],
        url=data["url"],
        kind=data["kind"],
        why=data.get("why"),
        label_directions=data.get("label_directions"),
    )


def current_plan(db: Session, plan: WellnessPlan) -> contract.CurrentPlan:
    """The plan as the Oracle gets it, with each item's id."""
    content = plan.content
    items = active_items(db, plan)
    pillars = []
    for code, data in (content.get("pillars") or {}).items():
        healthy_four = data.get("healthy_four")
        pillars.append(
            contract.PlanPillar(
                code=code,
                adjustment=data.get("adjustment"),
                sacred_seven=bool(data.get("sacred_seven")),
                healthy_four=(
                    [contract.HealthyFourTarget(**target) for target in healthy_four]
                    if healthy_four
                    else None
                ),
                insulin_resistance_phase=data.get("insulin_resistance_phase"),
            )
        )
    return contract.CurrentPlan(
        clinical_summary=content["clinical_summary"],
        immediate_dietary_action=content.get("immediate_dietary_action"),
        focus_areas=[
            contract.PlanFocusArea(
                id=str(item.id),
                title=item.title,
                recommendations=list(item.details.get("recommendations") or []),
                time_frame=item.details.get("time_frame"),
            )
            for item in items
            if item.kind == "focus_area"
        ],
        todos=[
            contract.PlanTodo(
                id=str(item.id),
                text=item.title,
                protocol=item.details.get("protocol"),
                product=(
                    _recommendation(item.details["product"])
                    if item.details.get("product")
                    else None
                ),
                done=item.status == "done",
            )
            for item in items
            if item.kind == "todo"
        ],
        pillars=pillars,
        products=[_recommendation(data) for data in content.get("products") or []],
        notices=list(content.get("notices") or []),
    )


def oracle_plan(db: Session, profile: Profile) -> contract.CurrentPlan | None:
    """For ProfileContext.wellness_plan (the conversations package fills it in): every new
    conversation uses the plan as context, and follows up on items that are due (7.1)."""
    plan = plan_row(db, profile)
    if plan is None or plan.version == 0:
        return None
    return current_plan(db, plan)
