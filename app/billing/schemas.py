"""The plan screen (story 9.1) and Subscription & Billing (story 11.3)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator

from app.billing.catalog import PaidPlan
from app.billing.entitlements import Feature, Plan
from app.core.config import settings
from app.core.schemas import RequestBody
from app.profiles.schemas import CHOOSE_AN_OPTION

# 11.3's statuses (Trial, Active, Payment issue, Cancelled), plus "ended": a subscription that
# has run out, which is locked as when a trial ends.
Status = Literal["trial", "active", "payment_issue", "cancelled", "ended"]
# Where the subscription is managed: in the app, or in a store (11.3).
ManagedBy = Literal["app", "app_store", "google_play"]

# Not in the stories (docs/decisions/phase-8-billing.md).
CONFIRM_PRICE = "Please confirm the price to continue."


class Price(BaseModel):
    amount_cents: int
    currency: str
    display: str  # "$19.99"


class PlanOut(BaseModel):
    code: PaidPlan
    name: str
    monthly_price: Price
    family_members_included: int
    features: list[str]  # 9.1's "what's included", in order


class PlansOut(BaseModel):
    """Story 9.1's plan screen. Every price comes from one place (app/billing/catalog.py)."""

    plans: list[PlanOut]
    # Each family member beyond the Family plan's places (Family plan only).
    add_on_monthly_price: Price
    renewal_disclaimer: str
    # "Adding [Name] will add $9.99 a month to your subscription. Continue?": the app fills
    # in [Name], as with the other labels that name someone.
    add_on_confirmation: str
    trial_days: int


class PaymentMethodOut(BaseModel):
    brand: str  # "visa", "apple_pay"... the app shows "Visa ending 4417" or "Apple Pay"
    last4: str | None


class SubscriptionOut(BaseModel):
    """Story 11.3's current plan, and what the app needs around it."""

    plan: Plan  # "trial" when there's no subscription
    plan_name: str  # "Free trial", "Individual", "Family"
    status: Status
    # Whether the client can use the plan's features now (False once a trial or plan ends).
    has_access: bool
    trial_ends_at: datetime
    trial_days_left: int | None  # 9.1's days left, while on the trial
    # When access ends after a cancellation or a failed payment; null while it renews.
    access_until: datetime | None
    next_billing_at: datetime | None
    next_billing_amount: Price | None
    # A downgrade waiting for the next billing date.
    scheduled_plan: PaidPlan | None
    # Family plan only: "3 of 3 active family members", and the add-ons with their price.
    family_members_used: int | None
    family_members_included: int | None
    add_on_members: int
    add_on_monthly_price: Price | None
    payment_method: PaymentMethodOut | None
    managed_by: ManagedBy | None
    renewal_disclaimer: str | None
    # The status's notice: payment issue, cancelled, trial or subscription ended.
    message: str | None
    # Texts to confirm before POST .../cancel and the downgrade, with the date filled in.
    cancel_confirmation: str | None
    downgrade_confirmation: str | None
    # Family members the plan's end turned off, waiting to be turned back on, and 11.3's
    # "Choose who to turn back on" when they don't all fit in the plan's places.
    family_members_waiting: int
    choose_family_members: str | None
    # 9.1's greyed-out features (each one shows the upgrade prompt).
    locked_features: list[Feature]


class SubscriptionResult(BaseModel):
    message: str | None
    # Set when the provider's page has to be opened to pay; the subscription starts once the
    # payment goes through, a few seconds after the client comes back.
    checkout_url: str | None = None
    subscription: SubscriptionOut


def _known_plan(value: object, handler) -> PaidPlan:
    """An unknown or missing plan gets the stories' "Please choose an option to continue."."""
    try:
        plan = handler(value)
    except ValidationError:
        raise ValueError(CHOOSE_AN_OPTION) from None
    if plan is None:
        raise ValueError(CHOOSE_AN_OPTION)
    return plan


def _confirmed(value: int | None) -> int:
    if value is None:
        raise ValueError(CONFIRM_PRICE)
    return value


def _add_on_count(value: int, lowest: int) -> int:
    if not lowest <= value <= settings.max_add_on_members:
        raise ValueError(f"You can add up to {settings.max_add_on_members} extra family members.")
    return value


class StartSubscription(RequestBody):
    """Subscribe (9.1). The client confirms the monthly total they were shown (the plan plus
    any add-ons) and the renewal disclaimer: a different total means the price changed."""

    plan: PaidPlan | None = None
    add_on_members: int = 0
    confirmed_monthly_price_cents: int | None = None

    @field_validator("plan", mode="wrap")
    @classmethod
    def check_plan(cls, value: object, handler) -> PaidPlan:
        return _known_plan(value, handler)

    @field_validator("add_on_members")
    @classmethod
    def check_add_ons(cls, value: int) -> int:
        return _add_on_count(value, 0)

    @field_validator("confirmed_monthly_price_cents")
    @classmethod
    def check_price(cls, value: int | None) -> int:
        return _confirmed(value)


class ChangePlan(RequestBody):
    """Individual to Family applies at once and needs the new monthly total confirmed (checked
    by the service); Family to Individual applies from the next billing date."""

    plan: PaidPlan | None = None
    confirmed_monthly_price_cents: int | None = None

    @field_validator("plan", mode="wrap")
    @classmethod
    def check_plan(cls, value: object, handler) -> PaidPlan:
        return _known_plan(value, handler)


class AddOns(RequestBody):
    """More places on the Family plan (9.1's add-on). The confirmed price is the add-ons'
    monthly price, from the add-on confirmation."""

    count: int = 1
    confirmed_monthly_price_cents: int | None = None

    @field_validator("count")
    @classmethod
    def check_count(cls, value: int) -> int:
        return _add_on_count(value, 1)

    @field_validator("confirmed_monthly_price_cents")
    @classmethod
    def check_price(cls, value: int | None) -> int:
        return _confirmed(value)


class PaymentMethodLink(BaseModel):
    """The provider's page for changing the payment method. When the client comes back, the
    app shows 11.3's "Your payment method has been updated."."""

    url: str


class InvoiceOut(BaseModel):
    id: uuid.UUID
    issued_at: datetime
    amount: Price
    status: Literal["paid", "failed"]
    plan: PaidPlan | None
    receipt_url: str | None  # the downloadable receipt, where the provider has one


class BillingHistoryOut(BaseModel):
    invoices: list[InvoiceOut]  # newest first
    # "There's no billing history yet.", or where a store subscription's history is kept.
    message: str | None


class WebhookReceived(BaseModel):
    received: bool = True
