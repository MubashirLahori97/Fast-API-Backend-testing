"""The plans, their prices and what they include (stories 9.1 and 11.3).

This is the one place prices are read from. The Super Admin edits them in the admin panel
(Super Admin stories 8.1 and 8.2, app/admin/plans/), which saves them in `billing_plans`, one
row per plan with its price history in `billing_plan_price_changes`. A launch plan (the free
trial, Individual and Family) with no row yet uses the settings (assumed values, see
docs/decisions/phase-8-billing.md), so a new database works before anyone opens the admin
panel.

The functions here take no database session, so billing's callers didn't change. They read a
copy of the launch plans' rows that each process keeps for `settings.plan_catalog_cache_seconds`
and then reads again with its own short session. The admin panel calls `refresh(db)` after each
change, so its own process sees it at once; other processes (the worker, other API servers) see
it within the cache time. Tests that change plans call `refresh(db)` or `clear_cache()`.

Prices are whole cents, in `settings.billing_currency` (US dollars).
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import settings
from app.core.database import Base, SessionLocal

logger = logging.getLogger(__name__)

PaidPlan = Literal["individual", "family"]
PAID_PLANS: tuple[PaidPlan, ...] = ("individual", "family")
PlanType = Literal["trial", "individual", "family"]
PlanStatus = Literal["draft", "active", "inactive"]
# The plans at launch (Super Admin 8.1, Session 9). Their codes are what subscriptions store.
LAUNCH_CODES = ("trial", "individual", "family")

TRIAL_NAME = "Free trial"
# Story 9.1's plan screen, and 11.3's shorter version on the current plan.
RENEWAL_DISCLAIMER = (
    "Your subscription renews automatically each month until you cancel. "
    "You can cancel anytime in Profile & Account."
)
RENEWAL_DISCLAIMER_SHORT = "Your subscription renews automatically each month until you cancel."


class BillingPlan(Base):
    """A plan the admin panel manages (Super Admin 8.1 and 8.2). Plans are never deleted, only
    made inactive, so their history can always be traced.

    - `code`: what subscriptions store. The launch plans are `trial`, `individual` and
      `family`; a plan the Super Admin adds gets a code from its name.
    - `plan_type`: trial (one only, with its length in days), individual (a monthly price) or
      family (a monthly price, the family members included and the price of each add-on).
    - `status`: draft (not shown to clients), active, or inactive (new clients can't choose
      it; clients already on it keep it).
    - `features`: "what's included", one line each, as the plan screen shows them."""

    __tablename__ = "billing_plans"
    __table_args__ = (
        CheckConstraint(
            "plan_type IN ('trial', 'individual', 'family')", name="ck_billing_plans_type"
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'inactive')", name="ck_billing_plans_status"
        ),
        CheckConstraint(
            "(plan_type = 'trial') = (trial_days IS NOT NULL)", name="ck_billing_plans_trial_days"
        ),
        CheckConstraint(
            "(plan_type = 'trial') = (monthly_price_cents IS NULL)",
            name="ck_billing_plans_monthly_price",
        ),
        CheckConstraint(
            "(plan_type = 'family') = (family_members_included IS NOT NULL)",
            name="ck_billing_plans_family_members",
        ),
        CheckConstraint(
            "(plan_type = 'family') = (add_on_price_cents IS NOT NULL)",
            name="ck_billing_plans_add_on_price",
        ),
        CheckConstraint(
            "monthly_price_cents > 0 AND add_on_price_cents > 0 AND trial_days > 0 "
            "AND family_members_included > 0",
            name="ck_billing_plans_positive",
        ),
        # 8.2: "A plan with this name already exists.", whatever the case.
        Index("uq_billing_plans_name", func.lower(text("name")), unique=True),
        # 8.2: there's only one Free trial.
        Index(
            "uq_billing_plans_one_trial",
            "plan_type",
            unique=True,
            postgresql_where=text("plan_type = 'trial'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(unique=True)
    plan_type: Mapped[str]
    name: Mapped[str]
    status: Mapped[str]
    monthly_price_cents: Mapped[int | None]
    trial_days: Mapped[int | None]
    family_members_included: Mapped[int | None]
    add_on_price_cents: Mapped[int | None]
    features: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PlanPriceChange(Base):
    """8.1's price history: the plan's prices (or trial length, or family members included)
    from `changed_at`, and who set them. The first row is the plan's starting values, with no
    `changed_by_id` for the launch plans' values from the settings."""

    __tablename__ = "billing_plan_price_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="CASCADE"), index=True
    )
    monthly_price_cents: Mapped[int | None]
    add_on_price_cents: Mapped[int | None]
    trial_days: Mapped[int | None]
    family_members_included: Mapped[int | None]
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))


@dataclass(frozen=True)
class PlanValues:
    """One plan's current values, from its row or the settings."""

    code: str
    plan_type: PlanType
    name: str
    status: PlanStatus
    monthly_price_cents: int | None
    trial_days: int | None
    family_members_included: int | None
    add_on_price_cents: int | None
    features: tuple[str, ...]


@dataclass(frozen=True)
class Offer:
    """One plan as the plan screen shows it."""

    plan: PaidPlan
    name: str
    monthly_price_cents: int
    family_members_included: int
    # 9.1's "what's included", written to the client ("your own profile" for "the Client's").
    features: tuple[str, ...]
    # False once the Super Admin makes the plan inactive: new clients can't choose it, and
    # clients already on it keep it (Super Admin 8.1).
    available: bool = True


def default_values(code: str) -> PlanValues:
    """A launch plan's values from the settings, used until the admin panel saves its row."""
    if code == "trial":
        return PlanValues(
            code="trial",
            plan_type="trial",
            name=TRIAL_NAME,
            status="active",
            monthly_price_cents=None,
            trial_days=settings.trial_days,
            family_members_included=None,
            add_on_price_cents=None,
            features=(
                "your own profile only",
                "conversations with the Oracle",
            ),
        )
    if code == "individual":
        return PlanValues(
            code="individual",
            plan_type="individual",
            name=settings.individual_plan_name,
            status="active",
            monthly_price_cents=settings.individual_price_cents,
            trial_days=None,
            family_members_included=None,
            add_on_price_cents=None,
            features=(
                "unlimited conversations with the Oracle",
                "personalised guidance",
                "provider-ready notes to download and print",
                "My Visit Notes and visit logging",
                "My Health",
                "a Wellness Plan",
                "your own profile only",
            ),
        )
    if code == "family":
        included = settings.family_members_included
        return PlanValues(
            code="family",
            plan_type="family",
            name=settings.family_plan_name,
            status="active",
            monthly_price_cents=settings.family_price_cents,
            trial_days=None,
            family_members_included=included,
            add_on_price_cents=settings.family_add_on_price_cents,
            features=(
                f"everything in the {settings.individual_plan_name} plan",
                f"you plus {included} family {'member' if included == 1 else 'members'}, "
                "each with their own Wellness Plan",
                "inviting teens to their own account",
            ),
        )
    raise ValueError(f"Not a launch plan: {code}")


def values_from_row(row: BillingPlan) -> PlanValues:
    return PlanValues(
        code=row.code,
        plan_type=row.plan_type,
        name=row.name,
        status=row.status,
        monthly_price_cents=row.monthly_price_cents,
        trial_days=row.trial_days,
        family_members_included=row.family_members_included,
        add_on_price_cents=row.add_on_price_cents,
        features=tuple(row.features or ()),
    )


# The cached copy of the launch plans' rows

_lock = threading.Lock()
_cache: dict[str, PlanValues] | None = None
_cache_loaded_at = 0.0


def refresh(db: Session) -> None:
    """Reads the launch plans' rows again, in the caller's session. The admin panel calls it
    after each change it commits."""
    global _cache, _cache_loaded_at
    rows = db.scalars(select(BillingPlan).where(BillingPlan.code.in_(LAUNCH_CODES)))
    loaded = {row.code: values_from_row(row) for row in rows}
    with _lock:
        _cache = loaded
        _cache_loaded_at = time.monotonic()


def clear_cache() -> None:
    """Forgets the cached rows, so the next read loads them again (for tests)."""
    global _cache, _cache_loaded_at
    with _lock:
        _cache = None
        _cache_loaded_at = 0.0


def _rows() -> dict[str, PlanValues]:
    global _cache, _cache_loaded_at
    fresh = time.monotonic() - _cache_loaded_at < settings.plan_catalog_cache_seconds
    if _cache is not None and fresh:
        return _cache
    try:
        with SessionLocal() as db:
            refresh(db)
    except SQLAlchemyError as exc:
        # Keep what we had (or the settings), and don't try again on every call.
        logger.warning("Couldn't read the plan catalogue: %s", type(exc).__name__)
        with _lock:
            if _cache is None:
                _cache = {}
            _cache_loaded_at = time.monotonic()
    return _cache or {}


def values(code: str) -> PlanValues:
    """A launch plan's current values."""
    return _rows().get(code) or default_values(code)


# What billing reads


def offer(plan: PaidPlan) -> Offer:
    current = values(plan)
    return Offer(
        plan=plan,
        name=current.name,
        monthly_price_cents=current.monthly_price_cents,
        family_members_included=current.family_members_included or 0,
        features=current.features,
        available=current.status == "active",
    )


def offers() -> list[Offer]:
    """The plans new clients can choose (9.1's plan screen). An inactive plan isn't offered."""
    return [offer(plan) for plan in PAID_PLANS if values(plan).status == "active"]


def is_available(plan: PaidPlan) -> bool:
    """Whether a new subscriber can choose the plan (Super Admin 8.1's Inactive)."""
    return values(plan).status == "active"


def add_on_price_cents() -> int:
    """The monthly price of each family member beyond the Family plan's places."""
    return values("family").add_on_price_cents


def family_members_included() -> int:
    """The family members the Family plan includes, besides the account holder."""
    return values("family").family_members_included


def trial_days() -> int:
    """The free trial's length for new trials (Super Admin 8.1: trials already started keep
    their own length, since each account stores when its trial ends)."""
    return values("trial").trial_days


def plan_name(plan: str) -> str:
    """ "Free trial", or the paid plan's name ("Individual", "Family")."""
    return offer(plan).name if plan in PAID_PLANS else values("trial").name


def monthly_total_cents(plan: PaidPlan, add_on_members: int = 0) -> int:
    """What the plan costs a month today, with its add-ons (Family plan only)."""
    total = offer(plan).monthly_price_cents
    if plan == "family":
        total += add_on_members * add_on_price_cents()
    return total


def format_price(cents: int) -> str:
    """$19.99. Only US dollars are sold (sign-up is US only)."""
    return f"${cents // 100:,}.{cents % 100:02d}"
