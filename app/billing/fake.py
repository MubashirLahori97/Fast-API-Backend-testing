"""A stand-in payment provider, for development and tests. It takes no money."""

import calendar
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.billing.catalog import PaidPlan
from app.billing.provider import (
    Charge,
    Checkout,
    CheckoutRequest,
    EventType,
    InvalidEvent,
    InvalidSignature,
    PaymentCancelled,
    PaymentDeclined,
    PaymentMethod,
    PlanSetup,
    ProviderError,
    ProviderEvent,
    Started,
)
from app.core.config import settings

# Webhooks from the fake carry `Payment-Signature: t=<unix time>,v1=<hex>`, where the hex is
# the HMAC-SHA256 of "<t>.<body>" with settings.payment_webhook_secret. The time stops an old
# event being sent again later; the event id stops the same one being handled twice.
SIGNATURE_HEADER = "payment-signature"


def add_month(moment: datetime) -> datetime:
    """The same time a calendar month later; 31 January becomes 28 or 29 February."""
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def sign(body: bytes, timestamp: int | None = None) -> str:
    """The Payment-Signature header for a webhook body."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        settings.payment_webhook_secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


class _ChargeBody(BaseModel):
    invoice_id: str
    amount_cents: int
    currency: str = "usd"
    at: datetime
    receipt_url: str | None = None


class _PaymentMethodBody(BaseModel):
    brand: str
    last4: str | None = None


class _EventBody(BaseModel):
    """The fake's webhook JSON. A real provider's adapter reads its own format into the same
    ProviderEvent."""

    id: str
    type: EventType
    subscription_id: str
    created: datetime
    customer_id: str | None = None
    account_id: uuid.UUID | None = None
    plan: PaidPlan | None = None
    add_on_members: int | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    charge: _ChargeBody | None = None
    payment_method: _PaymentMethodBody | None = None


class FakePaymentProvider:
    """Takes every payment straight away, with no page to open. Tests and developers can change
    what it does:

    - `checkout_result`: "succeeded" (the default), "declined", "cancelled", or "hosted" to
      answer with a checkout link, as Stripe would, so the subscription only starts when a
      payment_succeeded event is posted to POST /billing/webhook;
    - `decline_charges = True`: upgrades and added add-ons are declined;
    - `fail = True`: every call raises ProviderError, as when the provider is down;
    - `payment_method`: what the client "paid" with.

    `calls` lists the methods called, in order. `signed_event(...)` builds a webhook body and
    its headers, for renewals, failed payments and endings, which only the provider can start.
    Upgrades and add-ons aren't charged straight away here: a real provider sends their
    invoices as payment_succeeded events.
    """

    name: Literal["fake"] = "fake"

    def __init__(self) -> None:
        if settings.environment == "production":
            raise RuntimeError("The fake payment provider can't be used in production.")
        self.checkout_result: Literal["succeeded", "declined", "cancelled", "hosted"] = "succeeded"
        self.decline_charges = False
        self.fail = False
        self.payment_method = PaymentMethod(brand="visa", last4="4242")
        self.calls: list[str] = []

    def _call(self, method: str) -> None:
        self.calls.append(method)
        if self.fail:
            raise ProviderError(f"The fake provider's {method} failed, as asked.")

    def start_checkout(self, request: CheckoutRequest) -> Checkout:
        self._call("start_checkout")
        if self.checkout_result == "declined":
            raise PaymentDeclined
        if self.checkout_result == "cancelled":
            raise PaymentCancelled
        subscription_id = f"fake_sub_{uuid.uuid4().hex}"
        customer_id = request.customer_id or f"fake_cus_{uuid.uuid4().hex}"
        if self.checkout_result == "hosted":
            return Checkout(url=f"{request.return_url}?checkout=fake&id={subscription_id}")
        now = datetime.now(UTC)
        amount = request.plan_price_cents
        if request.plan == "family":
            amount += request.add_on_members * request.add_on_price_cents
        return Checkout(
            started=Started(
                customer_id=customer_id,
                subscription_id=subscription_id,
                period_start=now,
                period_end=add_month(now),
                charge=Charge(
                    invoice_id=f"fake_in_{uuid.uuid4().hex}",
                    amount_cents=amount,
                    currency=request.currency,
                    at=now,
                ),
                payment_method=self.payment_method,
            )
        )

    def cancel(self, subscription_id: str, *, at_period_end: bool) -> None:
        self._call("cancel")

    def resume(self, subscription_id: str) -> None:
        self._call("resume")

    def change_plan(
        self,
        subscription_id: str,
        plan: PaidPlan,
        *,
        monthly_price_cents: int,
        at_period_end: bool,
    ) -> Charge | None:
        self._call("change_plan")
        if not at_period_end and self.decline_charges:
            raise PaymentDeclined
        return None

    def set_add_on_members(
        self, subscription_id: str, count: int, *, price_cents: int, prorate: bool
    ) -> Charge | None:
        self._call("set_add_on_members")
        if prorate and self.decline_charges:
            raise PaymentDeclined
        return None

    def payment_method_link(self, customer_id: str, return_url: str) -> str:
        self._call("payment_method_link")
        return f"{return_url}?payment_method=updated"

    def use_current_prices(self, subscription_id: str, plan: PaidPlan) -> None:
        self._call("use_current_prices")

    def set_up_plan(self, plan: PlanSetup) -> PlanSetup:
        """The fake sells any plan at any price, so there's nothing to set up or store."""
        self._call("set_up_plan")
        return plan

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        parts = dict(
            part.split("=", 1)
            for part in headers.get(SIGNATURE_HEADER, "").split(",")
            if "=" in part
        )
        try:
            timestamp = int(parts["t"])
        except (KeyError, ValueError):
            raise InvalidSignature from None
        if abs(time.time() - timestamp) > settings.payment_webhook_tolerance_seconds:
            raise InvalidSignature
        expected = sign(body, timestamp).removeprefix(f"t={timestamp},v1=")
        if not hmac.compare_digest(expected, parts.get("v1", "")):
            raise InvalidSignature
        try:
            data = _EventBody.model_validate_json(body)
        except ValidationError:
            raise InvalidEvent from None
        return ProviderEvent(
            id=data.id,
            type=data.type,
            subscription_id=data.subscription_id,
            occurred_at=data.created,
            customer_id=data.customer_id,
            account_id=data.account_id,
            plan=data.plan,
            add_on_members=data.add_on_members,
            period_start=data.period_start,
            period_end=data.period_end,
            charge=Charge(**data.charge.model_dump()) if data.charge else None,
            payment_method=(
                PaymentMethod(**data.payment_method.model_dump()) if data.payment_method else None
            ),
        )

    def signed_event(
        self, type: EventType, subscription_id: str, **fields: Any
    ) -> tuple[bytes, dict[str, str]]:
        """A webhook body and headers, as the fake would send them. `fields` are the other
        _EventBody fields; datetimes and UUIDs may be passed as they are."""
        event = {
            "id": f"fake_evt_{uuid.uuid4().hex}",
            "type": type,
            "subscription_id": subscription_id,
            "created": datetime.now(UTC),
            **fields,
        }
        body = json.dumps(event, default=str).encode()
        return body, {SIGNATURE_HEADER: sign(body), "content-type": "application/json"}
