"""Subscription & Billing management (Super Admin stories 8.1 and 8.2). Super Admin only: the
router uses SuperAdminSession, and these functions check the role again.

- **The launch plans** (Free trial, Individual, Family) get their `billing_plans` rows from the
  settings the first time the admin panel opens, so the listing always shows them.
- **Editing** (8.1) saves straight away and records the price history. The catalogue is read
  again at once in this process (and within its cache time elsewhere):
    - new subscribers pay a new price straight away; existing subscribers pay it from their next
      billing date, because billing stores each period's price and refreshes it at renewal;
    - existing subscribers are emailed about a price change (the `admin_plans.price_change_*`
      jobs), with no health information;
    - a new trial length applies to new trials only, since each account stores when its trial
      ends.
- **Inactive** plans aren't offered to new clients (catalog.offers); clients on them keep them.
- **New plans** (8.2) are saved as drafts. Publishing needs the payment providers to sell them
  (PAYMENT PROVIDERS below); until billing supports plans beyond Individual and Family, it
  answers 8.2's "We couldn’t set up this plan..." and the plan stays a draft.
"""

import re
import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.admin.common import is_teen, subscription_gives_access
from app.admin.plans import emails
from app.admin.plans.schemas import (
    MEMBERS_INVALID,
    PRICE_INVALID,
    TRIAL_INVALID,
    PersonRef,
    PlanDetail,
    PlanEdit,
    PlanList,
    PlanNew,
    PlanRow,
    PlanSaved,
    PriceChangeOut,
)
from app.auth.models import User
from app.billing import catalog
from app.billing.catalog import LAUNCH_CODES, PAID_PLANS, BillingPlan, PlanPriceChange
from app.billing.models import Subscription
from app.billing.schemas import Price
from app.core import audit, jobs
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import AppError, database_errors_retryable

PRICE_CHANGE_JOB = "admin_plans.price_change_emails"  # see app/admin/jobs.py
PRICE_CHANGE_EMAIL_JOB = "admin_plans.price_change_email"

# Super Admin 8.1 and 8.2's messages.
PRICE_CONFIRMATION = (
    "Change the price to {price}? New subscribers will pay this straight away. Existing "
    "subscribers will pay it from their next billing date, after they’ve been told."
)
INACTIVE_CONFIRMATION = (
    "Make this plan inactive? New Clients won’t be able to choose it. Clients already on it will "
    "keep it."
)
SAVED = "Your changes have been saved."
NAME_TAKEN = "A plan with this name already exists."
PUBLISH_CONFIRMATION = "Publish {name}? It will be shown to Clients on the plan screen."
DRAFT_SAVED = "Your draft has been saved."
PUBLISHED = "{name} is now available to Clients."
SETUP_FAILED = "We couldn’t set up this plan with the payment providers. Please try again."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
PLAN_NOT_FOUND = "We couldn’t find that plan."
NOT_FOR_THIS_PLAN = "This can’t be changed for this plan."
TRIAL_ALWAYS_ACTIVE = "The free trial can’t be made inactive."
NAME_FIXED = "A published plan’s name can’t be changed."
PUBLISH_FIRST = "Please publish this plan first."
ALREADY_PUBLISHED = "This plan has already been published."
SUPER_ADMIN_ONLY = "Only the Super Admin can do this."

# What each plan type lets the Super Admin change (8.1's Editing a Plan).
EDITABLE = {
    "trial": {"trial_days"},
    "individual": {"monthly_price_cents", "features", "status"},
    "family": {
        "monthly_price_cents",
        "features",
        "status",
        "family_members_included",
        "add_on_price_cents",
    },
}
PRICE_FIELDS = ("monthly_price_cents", "add_on_price_cents")
HISTORY_FIELDS = (
    "monthly_price_cents",
    "add_on_price_cents",
    "trial_days",
    "family_members_included",
)
NULL_MESSAGES = {
    "name": "Please enter a plan name.",
    "monthly_price_cents": PRICE_INVALID,
    "add_on_price_cents": PRICE_INVALID,
    "family_members_included": MEMBERS_INVALID,
    "trial_days": TRIAL_INVALID,
    "features": "Please add at least one feature.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _check_super_admin(admin: User) -> None:
    if admin.role != "super_admin":
        raise AppError(403, "super_admin_only", SUPER_ADMIN_ONLY)


def _price(cents: int | None) -> Price | None:
    if cents is None:
        return None
    return Price(
        amount_cents=cents, currency=settings.billing_currency, display=catalog.format_price(cents)
    )


def _history_row(plan: BillingPlan, changed_by_id: uuid.UUID | None) -> PlanPriceChange:
    return PlanPriceChange(
        plan_id=plan.id,
        changed_by_id=changed_by_id,
        **{field: getattr(plan, field) for field in HISTORY_FIELDS},
    )


def ensure_launch_plans(db: Session) -> None:
    """Saves the launch plans' rows from the settings if they aren't there yet. The caller
    commits."""
    for code in LAUNCH_CODES:
        values = catalog.default_values(code)
        inserted = db.scalar(
            insert(BillingPlan)
            .values(
                id=uuid.uuid4(),
                code=code,
                plan_type=values.plan_type,
                name=values.name,
                status="active",
                monthly_price_cents=values.monthly_price_cents,
                trial_days=values.trial_days,
                family_members_included=values.family_members_included,
                add_on_price_cents=values.add_on_price_cents,
                features=list(values.features),
                published_at=_now(),
            )
            .on_conflict_do_nothing()
            .returning(BillingPlan.id)
        )
        if inserted is not None:
            plan = db.get(BillingPlan, inserted)
            db.add(_history_row(plan, None))


def _client_counts(db: Session) -> dict[str, int]:
    now = _now()
    counts = dict(
        db.execute(
            select(Subscription.plan, func.count())
            .where(subscription_gives_access(now))
            .group_by(Subscription.plan)
        ).all()
    )
    counts["trial"] = db.scalar(
        select(func.count())
        .select_from(User)
        .outerjoin(Subscription, Subscription.account_id == User.id)
        .where(
            User.role == "client",
            ~is_teen(),
            Subscription.id.is_(None),
            User.trial_ends_at > now,
        )
    )
    return counts


def _row(plan: BillingPlan, counts: dict[str, int]) -> PlanRow:
    return PlanRow(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        plan_type=plan.plan_type,
        status=plan.status,
        monthly_price=_price(plan.monthly_price_cents),
        trial_days=plan.trial_days,
        family_members_included=plan.family_members_included,
        add_on_price=_price(plan.add_on_price_cents),
        clients=counts.get(plan.code, 0),
    )


def _person(db: Session, user_id: uuid.UUID | None) -> PersonRef | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return PersonRef(id=user_id, first_name=user.first_name if user else None)


def _detail(db: Session, plan: BillingPlan) -> PlanDetail:
    history = db.scalars(
        select(PlanPriceChange)
        .where(PlanPriceChange.plan_id == plan.id)
        .order_by(PlanPriceChange.changed_at.desc())
    )
    return PlanDetail(
        **_row(plan, _client_counts(db)).model_dump(),
        features=list(plan.features or []),
        price_history=[
            PriceChangeOut(
                monthly_price=_price(change.monthly_price_cents),
                add_on_price=_price(change.add_on_price_cents),
                trial_days=change.trial_days,
                family_members_included=change.family_members_included,
                changed_by=_person(db, change.changed_by_id),
                changed_at=change.changed_at,
            )
            for change in history
        ],
        published_at=plan.published_at,
        created_at=plan.created_at,
        set_inactive_confirmation=INACTIVE_CONFIRMATION if plan.status == "active" else None,
    )


def _load(db: Session, plan_id: uuid.UUID, *, lock: bool = False) -> BillingPlan:
    plan = db.get(BillingPlan, plan_id, with_for_update=lock)
    if plan is None:
        raise AppError(404, "plan_not_found", PLAN_NOT_FOUND)
    return plan


def list_plans(db: Session, admin: User) -> PlanList:
    """8.1's listing: the launch plans first, then the others, oldest first."""
    _check_super_admin(admin)
    with database_errors_retryable(db):
        ensure_launch_plans(db)
        db.commit()
    order = {code: index for index, code in enumerate(LAUNCH_CODES)}
    plans = sorted(
        db.scalars(select(BillingPlan)),
        key=lambda plan: (order.get(plan.code, len(order)), plan.created_at),
    )
    counts = _client_counts(db)
    return PlanList(items=[_row(plan, counts) for plan in plans])


def get_plan(db: Session, admin: User, plan_id: uuid.UUID) -> PlanDetail:
    _check_super_admin(admin)
    return _detail(db, _load(db, plan_id))


def _name_taken(db: Session, name: str, plan_id: uuid.UUID | None = None) -> bool:
    query = select(BillingPlan.id).where(func.lower(BillingPlan.name) == name.lower())
    if plan_id is not None:
        query = query.where(BillingPlan.id != plan_id)
    return db.scalar(query) is not None


def _confirm(confirmed: bool, message: str) -> None:
    if not confirmed:
        raise AppError(409, "confirmation_required", message)


def update_plan(
    db: Session, admin: User, plan_id: uuid.UUID, body: PlanEdit, request: Request | None = None
) -> PlanSaved:
    _check_super_admin(admin)
    sent = body.model_fields_set - {"confirmed"}
    with database_errors_retryable(db):
        plan = _load(db, plan_id, lock=True)
        allowed = EDITABLE[plan.plan_type] | ({"name"} if plan.status == "draft" else set())
        for field in sorted(sent):
            if getattr(body, field) is None:
                raise AppError(
                    422, "validation_error", NULL_MESSAGES.get(field, PRICE_INVALID), field
                )
            if field == "name" and plan.status != "draft":
                raise AppError(422, "name_fixed", NAME_FIXED, field)
            if field == "status" and plan.plan_type == "trial":
                raise AppError(422, "trial_always_active", TRIAL_ALWAYS_ACTIVE, field)
            if field not in allowed:
                raise AppError(422, "not_editable", NOT_FOR_THIS_PLAN, field)
        if body.status is not None and plan.status == "draft":
            raise AppError(422, "publish_first", PUBLISH_FIRST, "status")
        changes = {
            field: getattr(body, field)
            for field in sent
            if getattr(body, field) != getattr(plan, field)
        }
        if "features" in changes and list(plan.features or []) == changes["features"]:
            del changes["features"]
        if "name" in changes and _name_taken(db, changes["name"], plan.id):
            raise AppError(409, "plan_name_taken", NAME_TAKEN, "name")
        price_changed = [field for field in PRICE_FIELDS if field in changes]
        if price_changed and plan.status != "draft":
            _confirm(
                body.confirmed,
                PRICE_CONFIRMATION.format(price=catalog.format_price(changes[price_changed[0]])),
            )
        if changes.get("status") == "inactive":
            _confirm(body.confirmed, INACTIVE_CONFIRMATION)
        if not changes:
            db.rollback()
            return PlanSaved(plan=_detail(db, plan), message=SAVED)

        before = {field: getattr(plan, field) for field in changes if field != "features"}
        for field, value in changes.items():
            setattr(plan, field, value)
        plan.updated_at = _now()
        change = None
        if any(field in changes for field in HISTORY_FIELDS):
            change = _history_row(plan, admin.id)
            db.add(change)
            db.flush()
        audit.record(
            db,
            "billing.plan_changed",
            actor_id=admin.id,
            target_type="billing_plan",
            target_id=plan.id,
            request=request,
            details={
                "code": plan.code,
                "fields": sorted(changes),
                "from": {k: v for k, v in before.items() if k != "status"},
                "to": {k: v for k, v in changes.items() if k not in ("features", "status")},
                **(
                    {"status": [before["status"], changes["status"]]} if "status" in changes else {}
                ),
            },
        )
        # PAYMENT PROVIDERS: update the plan's prices with Stripe, the App Store and Google Play
        # (app/billing/provider.py has no call for it yet). 8.1's "Store update pending" message
        # belongs here once store prices exist.
        if price_changed and plan.status != "draft" and plan.code in PAID_PLANS:
            jobs.enqueue(
                db,
                PRICE_CHANGE_JOB,
                {
                    "plan_code": plan.code,
                    "price_change_id": str(change.id),
                    "monthly": "monthly_price_cents" in changes,
                    "add_on": "add_on_price_cents" in changes,
                },
            )
        db.commit()
    catalog.refresh(db)
    return PlanSaved(plan=_detail(db, plan), message=SAVED)


def _code_for(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "plan"
    code, number = base, 2
    while code in LAUNCH_CODES or db.scalar(select(BillingPlan.id).where(BillingPlan.code == code)):
        code, number = f"{base}_{number}", number + 1
    return code


def _set_up_with_providers(plan: BillingPlan) -> bool:
    """PAYMENT PROVIDERS: sets the plan up with Stripe, the App Store and Google Play (8.2).
    Billing sells only the Individual and Family plans today (subscriptions.plan, PaidPlan), so
    a new plan can't be set up yet and stays a draft. Returns True once it's set up."""
    return plan.code in PAID_PLANS


def create_plan(
    db: Session, admin: User, body: PlanNew, request: Request | None = None
) -> PlanSaved:
    """8.2's + Add plan. Save as draft, or Publish (with `confirmed`), which first saves the
    draft and then tries the payment providers."""
    _check_super_admin(admin)
    if body.action == "publish":
        _confirm(body.confirmed, PUBLISH_CONFIRMATION.format(name=body.name))
    with database_errors_retryable(db):
        ensure_launch_plans(db)
        if _name_taken(db, body.name):
            raise AppError(409, "plan_name_taken", NAME_TAKEN, "name")
        plan = BillingPlan(
            code=_code_for(db, body.name),
            plan_type=body.plan_type,
            name=body.name,
            status="draft",
            monthly_price_cents=body.monthly_price_cents,
            family_members_included=body.family_members_included,
            add_on_price_cents=body.add_on_price_cents,
            features=body.features,
            created_by_id=admin.id,
        )
        db.add(plan)
        db.flush()
        db.add(_history_row(plan, admin.id))
        audit.record(
            db,
            "billing.plan_added",
            actor_id=admin.id,
            target_type="billing_plan",
            target_id=plan.id,
            request=request,
            details={"code": plan.code, "plan_type": plan.plan_type, "status": "draft"},
        )
        db.commit()
    if body.action == "publish":
        return publish_plan(db, admin, plan.id, confirmed=True, request=request)
    return PlanSaved(plan=_detail(db, plan), message=DRAFT_SAVED)


def publish_plan(
    db: Session,
    admin: User,
    plan_id: uuid.UUID,
    *,
    confirmed: bool,
    request: Request | None = None,
) -> PlanSaved:
    """8.2's Publish: set up with the payment providers, then shown to clients as Active. If
    the setup fails, the plan stays a draft and can be published again."""
    _check_super_admin(admin)
    with database_errors_retryable(db):
        plan = _load(db, plan_id, lock=True)
        if plan.status != "draft":
            raise AppError(409, "already_published", ALREADY_PUBLISHED)
        _confirm(confirmed, PUBLISH_CONFIRMATION.format(name=plan.name))
        if not _set_up_with_providers(plan):
            audit.record(
                db,
                "billing.plan_setup_failed",
                actor_id=admin.id,
                target_type="billing_plan",
                target_id=plan.id,
                request=request,
                details={"code": plan.code},
            )
            db.commit()
            raise AppError(503, "plan_setup_failed", SETUP_FAILED)
        plan.status = "active"
        plan.published_at = _now()
        audit.record(
            db,
            "billing.plan_published",
            actor_id=admin.id,
            target_type="billing_plan",
            target_id=plan.id,
            request=request,
            details={"code": plan.code},
        )
        db.commit()
    catalog.refresh(db)
    return PlanSaved(plan=_detail(db, plan), message=PUBLISHED.format(name=plan.name))


# Telling existing subscribers about a price change (8.1), from app/admin/jobs.py


def queue_price_change_emails(db: Session, payload: dict) -> None:
    """One batch: queues an email for each subscriber on the plan who will renew, then the next
    batch. The worker commits."""
    after = payload.get("after_account_id")
    query = (
        select(Subscription.account_id)
        .join(User, User.id == Subscription.account_id)
        .where(
            Subscription.plan == payload["plan_code"],
            Subscription.status.in_(("active", "past_due")),
            Subscription.cancel_at_period_end.is_(False),
            User.status == "active",
        )
        .order_by(Subscription.account_id)
        .limit(settings.price_change_email_batch_size)
    )
    if after is not None:
        query = query.where(Subscription.account_id > uuid.UUID(after))
    account_ids = db.scalars(query).all()
    for account_id in account_ids:
        jobs.enqueue(
            db,
            PRICE_CHANGE_EMAIL_JOB,
            {key: payload[key] for key in ("plan_code", "price_change_id", "monthly", "add_on")}
            | {"account_id": str(account_id)},
        )
    if len(account_ids) == settings.price_change_email_batch_size:
        jobs.enqueue(db, PRICE_CHANGE_JOB, payload | {"after_account_id": str(account_ids[-1])})


def send_price_change_email(db: Session, payload: dict, send: SendEmail) -> None:
    """One subscriber's email. Skipped if they've left the plan, cancelled or been deactivated
    since. The worker commits."""
    account = db.get(User, uuid.UUID(payload["account_id"]))
    change = db.get(PlanPriceChange, uuid.UUID(payload["price_change_id"]))
    if account is None or change is None or account.status != "active":
        return
    sub = db.scalar(select(Subscription).where(Subscription.account_id == account.id))
    if sub is None or sub.plan != payload["plan_code"] or sub.cancel_at_period_end:
        return
    plan = db.get(BillingPlan, change.plan_id)
    send(
        emails.price_change(
            account.email,
            plan.name if plan else catalog.plan_name(payload["plan_code"]),
            change.monthly_price_cents if payload.get("monthly") else None,
            change.add_on_price_cents if payload.get("add_on") else None,
        )
    )
