"""Payments, behind one interface (stories 9.1 and 11.3).

Card payments go through Stripe (chosen 11 Nov, docs/decisions/stripe-billing.md):
StripeProvider (stripe_provider.py). FakePaymentProvider (fake.py) stands in for development and
tests when no Stripe key is set. get_payment_provider (dependencies.py) picks one. Code depends on
the PaymentProvider protocol, as it does for email and the Oracle. Apple and Google store
subscriptions (STORES) aren't sold yet.

The app never sees card details: checkout and the payment method page are the provider's own
hosted pages, and the provider's events (POST /billing/webhook) say what happened. The provider
never sees health data either: only the account's id and email, the plan and the prices.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.billing.catalog import PaidPlan

ProviderName = Literal["fake", "stripe", "app_store", "google_play"]
# Subscriptions bought in a store are managed there, not in the app (story 11.3).
STORES: dict[str, str] = {"app_store": "App Store", "google_play": "Google Play"}

EventType = Literal[
    "payment_succeeded",  # a payment went through: the first one, a renewal, or a retry
    "payment_failed",  # a payment was refused, such as a renewal on an expired card
    "subscription_renewed",  # a new billing period started
    "subscription_ended",  # the provider ended it: a cancellation reached the period end
    "payment_method_updated",  # the client changed their card on the provider's page
]


class PaymentDeclined(Exception):
    """The payment didn't go through (a declined card, not enough funds)."""


class PaymentCancelled(Exception):
    """The client cancelled the payment."""


class ProviderError(Exception):
    """Anything else, such as the provider being unreachable. Worth trying again."""


class InvalidSignature(Exception):
    """A webhook whose signature doesn't match, or that's too old: not from the provider."""


class InvalidEvent(Exception):
    """A signed webhook the provider sent in a shape we can't read."""


class IgnoredEvent(Exception):
    """A signed webhook about something billing doesn't follow (another event type, a one-off
    invoice). It's answered 200 so the provider doesn't send it again."""


@dataclass(frozen=True)
class PaymentMethod:
    """What the client paid with, as the provider describes it: never the card number."""

    brand: str  # "visa", "mastercard", "amex", "apple_pay", "google_pay"...
    last4: str | None = None  # cards only, for "Visa ending 4417"


@dataclass(frozen=True)
class Charge:
    """One invoice: what was charged, or tried."""

    invoice_id: str
    amount_cents: int
    currency: str
    at: datetime
    receipt_url: str | None = None  # the provider's downloadable receipt, where it has one


@dataclass(frozen=True)
class CheckoutRequest:
    account_id: uuid.UUID  # comes back on the first payment_succeeded event
    email: str
    customer_id: str | None  # the provider's customer, when the client subscribed before
    plan: PaidPlan
    add_on_members: int
    plan_price_cents: int
    add_on_price_cents: int
    currency: str
    return_url: str  # where the provider's page sends the client back


@dataclass(frozen=True)
class Started:
    """A subscription the provider has started and taken the first payment for."""

    customer_id: str
    subscription_id: str
    period_start: datetime
    period_end: datetime
    charge: Charge
    payment_method: PaymentMethod | None = None


@dataclass(frozen=True)
class Checkout:
    """Either `url`, a hosted page the app opens (the subscription starts when its
    payment_succeeded event arrives), or `started`, when it's already paid."""

    url: str | None = None
    started: Started | None = None


@dataclass(frozen=True)
class ProviderEvent:
    id: str  # the provider's event id: each one is handled once
    type: EventType
    subscription_id: str  # the provider's subscription id
    occurred_at: datetime
    customer_id: str | None = None
    # The first payment of a hosted checkout only: who it's for, from the CheckoutRequest.
    account_id: uuid.UUID | None = None
    plan: PaidPlan | None = None
    add_on_members: int | None = None
    # The billing period paid for, or started.
    period_start: datetime | None = None
    period_end: datetime | None = None
    charge: Charge | None = None
    payment_method: PaymentMethod | None = None


@dataclass(frozen=True)
class PlanSetup:
    """A plan as the provider sells it (Super Admin 8.1 and 8.2): its prices, and the provider's
    ids for them once it's been set up."""

    code: str  # billing_plans.code
    name: str
    monthly_price_cents: int
    currency: str
    add_on_price_cents: int | None = None  # Family plans: each extra family member
    price_id: str | None = None
    add_on_price_id: str | None = None


class PaymentProvider(Protocol):
    name: ProviderName

    def start_checkout(self, request: CheckoutRequest) -> Checkout:
        """Starts paying for a plan. Raises PaymentDeclined, PaymentCancelled or
        ProviderError."""
        ...

    def cancel(self, subscription_id: str, *, at_period_end: bool) -> None:
        """Stops renewing: at the end of the period paid for, or at once (a grace period that
        ran out, or a deleted account, 11.4). Ending one that has already ended does nothing."""
        ...

    def resume(self, subscription_id: str) -> None:
        """Undoes a cancellation before the period ends."""
        ...

    def change_plan(
        self,
        subscription_id: str,
        plan: PaidPlan,
        *,
        monthly_price_cents: int,
        at_period_end: bool,
    ) -> Charge | None:
        """An upgrade applies at once and is charged for the rest of the period (returns the
        charge, if one was taken straight away); a downgrade applies from the next billing
        date. Raises PaymentDeclined when an upgrade can't be paid."""
        ...

    def set_add_on_members(
        self, subscription_id: str, count: int, *, price_cents: int, prorate: bool
    ) -> Charge | None:
        """Sets how many add-on members the subscription pays for. Adding one is charged from
        that day (prorate); removing them takes effect for the next billing period."""
        ...

    def payment_method_link(self, customer_id: str, return_url: str) -> str:
        """A link to the provider's page where the client changes their payment method."""
        ...

    def use_current_prices(self, subscription_id: str, plan: PaidPlan) -> None:
        """After a price change (Super Admin 8.1): from the next billing date, the subscription
        is billed at the catalogue's current prices for `plan`, with nothing charged now."""
        ...

    def set_up_plan(self, plan: PlanSetup) -> PlanSetup:
        """Super Admin 8.1 and 8.2: makes the provider sell the plan at its prices. The first
        time, it creates the product and prices; a changed price becomes a new price, and the
        old one is archived (subscriptions on it keep it until use_current_prices moves them).
        Returns the plan with the provider's ids. Raises ProviderError."""
        ...

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        """Checks the webhook's signature and reads it. Raises InvalidSignature, InvalidEvent,
        IgnoredEvent, or ProviderError when the provider must be asked for more and can't be
        reached."""
        ...
