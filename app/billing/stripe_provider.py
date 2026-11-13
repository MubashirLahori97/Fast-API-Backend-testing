"""Stripe, the real payment provider (stories 9.1 and 11.3, Super Admin 8.1 and 8.2).

How each PaymentProvider call maps onto Stripe (docs/decisions/stripe-billing.md):

- start_checkout: a Checkout Session in subscription mode, with the plan's price and the add-on
  price as a quantity. The subscription starts when its checkout.session.completed or
  invoice.paid event arrives.
- change_plan: an upgrade swaps the plan's price at once and invoices the prorated difference
  straight away (`always_invoice`); if that payment fails, Stripe makes no change. A downgrade
  swaps the price with no proration, which in Stripe means "from the next invoice": the period
  already paid for stays on the Family plan.
- set_add_on_members: the quantity of the add-on price. Adding is invoiced at once, prorated;
  removing changes the next invoice only.
- cancel: `cancel_at_period_end`, or ending at once (grace period over, account deleted).
- payment_method_link: the Customer Portal, opened straight on its payment method page.
- parse_event: checks the Stripe-Signature header with the signing secret
  (stripe.Webhook.construct_event) and maps Stripe's events onto ProviderEvent.

Stripe only ever gets the account's id and email, the plan code and the prices: never health
data. Errors are logged by class and Stripe's error code only.
"""

import functools
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import stripe

from app.billing import catalog
from app.billing.catalog import PAID_PLANS, PaidPlan
from app.billing.provider import (
    Charge,
    Checkout,
    CheckoutRequest,
    IgnoredEvent,
    InvalidEvent,
    InvalidSignature,
    PaymentDeclined,
    PaymentMethod,
    PlanSetup,
    ProviderError,
    ProviderEvent,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "stripe-signature"
# Metadata on the prices this app creates, so a subscription's items can be told apart.
KIND_KEY = "genesis_kind"  # "plan" or "add_on"
PLAN_KEY = "genesis_plan"  # billing_plans.code
# Subscription metadata: who it's for, read when the first payment's event arrives.
ACCOUNT_KEY = "account_id"
# The add-ons a pending downgrade took off, put back if the client stays on Family.
ADD_ONS_BEFORE_DOWNGRADE_KEY = "add_ons_before_downgrade"
WALLETS = {"apple_pay", "google_pay"}


@functools.cache
def _client(api_key: str) -> stripe.StripeClient:
    # Network retries reuse an idempotency key, so a retried call is applied once.
    return stripe.StripeClient(api_key, max_network_retries=2)


@contextmanager
def _stripe_errors(action: str) -> Iterator[None]:
    """A declined card becomes PaymentDeclined; anything else from Stripe, ProviderError."""
    try:
        yield
    except stripe.CardError:
        raise PaymentDeclined from None
    except stripe.StripeError as error:
        logger.warning(
            "Stripe call failed (%s): %s %s", action, type(error).__name__, error.code or ""
        )
        raise ProviderError(action) from None


def _at(timestamp: int | None) -> datetime | None:
    return datetime.fromtimestamp(timestamp, UTC) if timestamp else None


def _period(subscription: dict) -> tuple[datetime | None, datetime | None]:
    """The billing period: on the subscription's items in current API versions, on the
    subscription itself in older ones."""
    items = (subscription.get("items") or {}).get("data") or []
    source = items[0] if items else subscription
    start = source.get("current_period_start") or subscription.get("current_period_start")
    end = source.get("current_period_end") or subscription.get("current_period_end")
    return _at(start), _at(end)


def _charge(invoice: dict | None, *, failed: bool = False) -> Charge | None:
    """An invoice as a Charge: what was paid, or what was due for a failed payment."""
    if not isinstance(invoice, dict):
        return None
    if not failed and invoice.get("status") != "paid":
        return None
    paid_at = (invoice.get("status_transitions") or {}).get("paid_at")
    return Charge(
        invoice_id=invoice["id"],
        amount_cents=invoice.get("amount_due" if failed else "amount_paid") or 0,
        currency=invoice.get("currency") or settings.billing_currency,
        at=_at(paid_at or invoice.get("created")) or datetime.now(UTC),
        receipt_url=invoice.get("hosted_invoice_url"),
    )


def _payment_method(method: dict | None) -> PaymentMethod | None:
    """ "Visa ending 4417", or Apple Pay or Google Pay for a card in a wallet."""
    if not isinstance(method, dict):
        return None
    card = method.get("card")
    if method.get("type") == "card" and card:
        wallet = (card.get("wallet") or {}).get("type")
        if wallet in WALLETS:
            return PaymentMethod(brand=wallet)
        return PaymentMethod(brand=card.get("brand") or "card", last4=card.get("last4"))
    return PaymentMethod(brand=method.get("type") or "other")


def _invoice_subscription(invoice: dict) -> tuple[str | None, dict]:
    """The subscription an invoice is for, and its metadata when the invoice was made."""
    details = (invoice.get("parent") or {}).get("subscription_details") or {}
    subscription = details.get("subscription") or invoice.get("subscription")
    if isinstance(subscription, dict):
        subscription = subscription.get("id")
    return subscription, details.get("metadata") or {}


def _id(value: Any) -> str | None:
    """An expandable field's id, whether Stripe sent the id or the object."""
    if isinstance(value, dict):
        return value.get("id")
    return value


class StripeProvider:
    name: Literal["stripe"] = "stripe"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.stripe_secret_key
        if not key:
            raise RuntimeError("STRIPE_SECRET_KEY isn't set.")
        self._stripe = _client(key)

    # Reading

    def _subscription(self, subscription_id: str, *expand: str) -> dict:
        params = {"expand": list(expand)} if expand else None
        return self._stripe.v1.subscriptions.retrieve(subscription_id, params).to_dict()

    def _price_id(self, plan: PaidPlan | str, *, expected_cents: int | None = None) -> str:
        """The catalogue's Stripe price for the plan (or "add_on"), checked against the price the
        client confirmed, so Stripe never charges a different amount from the one shown."""
        price_id = catalog.stripe_add_on_price_id() if plan == "add_on" else None
        if plan in PAID_PLANS:
            price_id = catalog.stripe_price_id(plan)
        if not price_id:
            logger.warning("No Stripe price is set up for %s.", plan)
            raise ProviderError("price not set up")
        if expected_cents is not None:
            price = self._stripe.v1.prices.retrieve(price_id).to_dict()
            if not price.get("active") or price.get("unit_amount") != expected_cents:
                logger.warning("The Stripe price for %s doesn't match the catalogue.", plan)
                raise ProviderError("price mismatch")
        return price_id

    @staticmethod
    def _is_add_on(item: dict) -> bool:
        price = item.get("price") or {}
        kind = (price.get("metadata") or {}).get(KIND_KEY)
        if kind:
            return kind == "add_on"
        return price.get("id") == catalog.stripe_add_on_price_id()

    def _items(self, subscription: dict) -> tuple[dict | None, dict | None]:
        """The subscription's plan item and add-on item (None when there are no add-ons)."""
        plan_item = add_on_item = None
        for item in (subscription.get("items") or {}).get("data") or []:
            if self._is_add_on(item):
                add_on_item = item
            elif plan_item is None:
                plan_item = item
        if plan_item is None:
            raise ProviderError("subscription has no plan item")
        return plan_item, add_on_item

    def _update(self, subscription_id: str, params: dict) -> dict:
        return self._stripe.v1.subscriptions.update(
            subscription_id, {**params, "expand": ["latest_invoice"]}
        ).to_dict()

    @staticmethod
    def _charged_now(updated: dict) -> Charge | None:
        """The invoice an `always_invoice` change paid straight away, if any."""
        invoice = updated.get("latest_invoice")
        if isinstance(invoice, dict) and invoice.get("billing_reason") == "subscription_update":
            return _charge(invoice)
        return None

    # The PaymentProvider calls

    def start_checkout(self, request: CheckoutRequest) -> Checkout:
        with _stripe_errors("start_checkout"):
            line_items = [
                {
                    "price": self._price_id(request.plan, expected_cents=request.plan_price_cents),
                    "quantity": 1,
                }
            ]
            if request.plan == "family" and request.add_on_members:
                add_on = self._price_id("add_on", expected_cents=request.add_on_price_cents)
                line_items.append({"price": add_on, "quantity": request.add_on_members})
            metadata = {
                ACCOUNT_KEY: str(request.account_id),
                PLAN_KEY: request.plan,
                "add_on_members": str(request.add_on_members),
            }
            params: dict[str, Any] = {
                "mode": "subscription",
                "line_items": line_items,
                "client_reference_id": str(request.account_id),
                "success_url": f"{request.return_url}?checkout=success",
                "cancel_url": f"{request.return_url}?checkout=cancelled",
                "subscription_data": {"metadata": metadata},
                "metadata": metadata,
                # Configured in Stripe's Checkout Studio (STRIPE_INTEGRATION_TODO.md). "hosted" is
                # the hosted page's name in stripe-python below 21.0.0 ("hosted_page" from 21).
                "ui_mode": "hosted",
                "billing_address_collection": "auto",
                "phone_number_collection": {"enabled": False},
                "automatic_tax": {"enabled": False},
                "allow_promotion_codes": False,
                "payment_method_collection": "always",
                "submit_type": "auto",
                "integration_identifier": "hosted_mobile_app_0001",
                "origin_context": "mobile_app",
            }
            if request.customer_id:
                params["customer"] = request.customer_id
            else:
                params["customer_email"] = request.email
            session = self._stripe.v1.checkout.sessions.create(params)
        return Checkout(url=session.url)

    def cancel(self, subscription_id: str, *, at_period_end: bool) -> None:
        with _stripe_errors("cancel"):
            if at_period_end:
                self._stripe.v1.subscriptions.update(
                    subscription_id, {"cancel_at_period_end": True}
                )
                return
            if self._subscription(subscription_id).get("status") == "canceled":
                return
            # Ends now, with no refund for the rest of the period and no final invoice.
            self._stripe.v1.subscriptions.cancel(
                subscription_id, {"prorate": False, "invoice_now": False}
            )

    def resume(self, subscription_id: str) -> None:
        with _stripe_errors("resume"):
            self._stripe.v1.subscriptions.update(subscription_id, {"cancel_at_period_end": False})

    def change_plan(
        self,
        subscription_id: str,
        plan: PaidPlan,
        *,
        monthly_price_cents: int,
        at_period_end: bool,
    ) -> Charge | None:
        with _stripe_errors("change_plan"):
            subscription = self._subscription(subscription_id)
            plan_item, add_on_item = self._items(subscription)
            metadata = subscription.get("metadata") or {}
            if not at_period_end:
                # 11.3's upgrade: at once, the difference for the rest of the period charged now.
                price = self._price_id(plan, expected_cents=monthly_price_cents)
                updated = self._update(
                    subscription_id,
                    {
                        "items": [{"id": plan_item["id"], "price": price}],
                        "proration_behavior": "always_invoice",
                        "payment_behavior": "error_if_incomplete",
                        "metadata": {PLAN_KEY: plan},
                    },
                )
                return self._charged_now(updated)
            items: list[dict[str, Any]] = [{"id": plan_item["id"], "price": self._price_id(plan)}]
            if plan == "individual":
                # 11.3's downgrade, from the next billing date: the next invoice is Individual,
                # with no add-ons. They're remembered in case the client stays on Family.
                removed = add_on_item["quantity"] if add_on_item else 0
                if add_on_item:
                    items.append({"id": add_on_item["id"], "deleted": True})
                new_metadata = {PLAN_KEY: plan, ADD_ONS_BEFORE_DOWNGRADE_KEY: str(removed)}
            else:
                # Staying on Family while a downgrade waits: back as it was.
                restore = int(metadata.get(ADD_ONS_BEFORE_DOWNGRADE_KEY) or 0)
                if restore and add_on_item is None:
                    items.append({"price": self._price_id("add_on"), "quantity": restore})
                new_metadata = {PLAN_KEY: plan, ADD_ONS_BEFORE_DOWNGRADE_KEY: ""}
            self._update(
                subscription_id,
                {"items": items, "proration_behavior": "none", "metadata": new_metadata},
            )
            return None

    def set_add_on_members(
        self, subscription_id: str, count: int, *, price_cents: int, prorate: bool
    ) -> Charge | None:
        with _stripe_errors("set_add_on_members"):
            subscription = self._subscription(subscription_id)
            _, item = self._items(subscription)
            current = item["quantity"] if item else 0
            if count == current:
                return None
            if item is None:
                expected = price_cents if prorate else None
                price = self._price_id("add_on", expected_cents=expected)
                change: dict[str, Any] = {"price": price, "quantity": count}
            elif count == 0:
                change = {"id": item["id"], "deleted": True}
            else:
                change = {"id": item["id"], "quantity": count}
            params: dict[str, Any] = {"items": [change]}
            if prorate:
                # 9.1: an add-on is charged from that day.
                params["proration_behavior"] = "always_invoice"
                params["payment_behavior"] = "error_if_incomplete"
            else:
                # 11.3: a removed add-on stops from the next billing date.
                params["proration_behavior"] = "none"
            updated = self._update(subscription_id, params)
            return self._charged_now(updated) if prorate else None

    def payment_method_link(self, customer_id: str, return_url: str) -> str:
        with _stripe_errors("payment_method_link"):
            session = self._stripe.v1.billing_portal.sessions.create(
                {
                    "customer": customer_id,
                    "return_url": return_url,
                    # Only the payment method page: cancelling and plan changes stay in the app.
                    "flow_data": {
                        "type": "payment_method_update",
                        "after_completion": {
                            "type": "redirect",
                            "redirect": {"return_url": f"{return_url}?payment_method=updated"},
                        },
                    },
                }
            )
        return session.url

    def use_current_prices(self, subscription_id: str, plan: PaidPlan) -> None:
        with _stripe_errors("use_current_prices"):
            subscription = self._subscription(subscription_id)
            plan_item, add_on_item = self._items(subscription)
            items = []
            plan_price = self._price_id(plan)
            if (plan_item.get("price") or {}).get("id") != plan_price:
                items.append({"id": plan_item["id"], "price": plan_price})
            if add_on_item is not None:
                add_on_price = self._price_id("add_on")
                if (add_on_item.get("price") or {}).get("id") != add_on_price:
                    items.append({"id": add_on_item["id"], "price": add_on_price})
            if items:
                self._stripe.v1.subscriptions.update(
                    subscription_id, {"items": items, "proration_behavior": "none"}
                )

    def set_up_plan(self, plan: PlanSetup) -> PlanSetup:
        with _stripe_errors("set_up_plan"):
            price_id = self._ensure_price(
                plan, "plan", plan.monthly_price_cents, plan.price_id, f"{plan.name} plan"
            )
            add_on_price_id = plan.add_on_price_id
            if plan.add_on_price_cents is not None:
                add_on_price_id = self._ensure_price(
                    plan,
                    "add_on",
                    plan.add_on_price_cents,
                    plan.add_on_price_id,
                    f"{plan.name} plan: extra family member",
                )
        return PlanSetup(
            code=plan.code,
            name=plan.name,
            monthly_price_cents=plan.monthly_price_cents,
            currency=plan.currency,
            add_on_price_cents=plan.add_on_price_cents,
            price_id=price_id,
            add_on_price_id=add_on_price_id,
        )

    def _ensure_price(
        self, plan: PlanSetup, kind: str, amount_cents: int, current_id: str | None, name: str
    ) -> str:
        """The monthly price at this amount: the current one if it already is, otherwise a new
        price on the same product (Stripe prices can't change), with the old one archived."""
        product_id = None
        if current_id:
            current = self._stripe.v1.prices.retrieve(current_id).to_dict()
            product_id = _id(current.get("product"))
            if (
                current.get("active")
                and current.get("unit_amount") == amount_cents
                and current.get("currency") == plan.currency
                and (current.get("recurring") or {}).get("interval") == "month"
            ):
                return current_id
        if product_id is None:
            product = self._stripe.v1.products.create(
                {"name": name, "metadata": {PLAN_KEY: plan.code, KIND_KEY: kind}},
                {"idempotency_key": f"genesis-product-{plan.code}-{kind}-{name}"},
            )
            product_id = product.id
        price = self._stripe.v1.prices.create(
            {
                "product": product_id,
                "unit_amount": amount_cents,
                "currency": plan.currency,
                "recurring": {"interval": "month"},
                "metadata": {PLAN_KEY: plan.code, KIND_KEY: kind},
            },
            {
                "idempotency_key": (
                    f"genesis-price-{plan.code}-{kind}-{amount_cents}-{current_id or 'first'}"
                )
            },
        )
        if current_id:
            # Subscriptions already on the old price keep it until use_current_prices.
            self._stripe.v1.prices.update(current_id, {"active": False})
        return price.id

    # Webhooks

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        secret = settings.stripe_webhook_secret
        if not secret:
            logger.warning("STRIPE_WEBHOOK_SECRET isn't set, so no webhook can be checked.")
            raise InvalidSignature
        try:
            event = stripe.Webhook.construct_event(
                body,
                headers.get(SIGNATURE_HEADER),
                secret,
                tolerance=settings.payment_webhook_tolerance_seconds,
            )
        except stripe.SignatureVerificationError:
            raise InvalidSignature from None
        except ValueError:
            raise InvalidEvent from None
        data = event.to_dict()
        handler = self._EVENTS.get(data.get("type"))
        if handler is None:
            raise IgnoredEvent
        try:
            with _stripe_errors("parse_event"):
                return handler(self, data)
        except (KeyError, TypeError, ValueError):
            raise InvalidEvent from None

    def _event(self, data: dict, **fields: Any) -> ProviderEvent:
        return ProviderEvent(
            id=data["id"], occurred_at=_at(data["created"]) or datetime.now(UTC), **fields
        )

    def _from_subscription(self, data: dict, subscription_id: str, charge: Charge | None):
        """The first payment, from checkout.session.completed or the first invoice.paid: who
        it's for (the subscription's metadata), its period and payment method. Whichever of the
        two arrives first starts the subscription; the other then changes nothing."""
        subscription = self._subscription(subscription_id, "default_payment_method")
        metadata = subscription.get("metadata") or {}
        start, end = _period(subscription)
        plan = metadata.get(PLAN_KEY)
        account = metadata.get(ACCOUNT_KEY)
        return self._event(
            data,
            type="payment_succeeded",
            subscription_id=subscription_id,
            customer_id=_id(subscription.get("customer")),
            account_id=UUID(account) if account else None,
            plan=plan if plan in PAID_PLANS else None,
            add_on_members=int(metadata.get("add_on_members") or 0),
            period_start=start,
            period_end=end,
            charge=charge,
            payment_method=_payment_method(subscription.get("default_payment_method")),
        )

    def _checkout_completed(self, data: dict) -> ProviderEvent:
        session = data["data"]["object"]
        paid = session.get("payment_status") in ("paid", "no_payment_required")
        if session.get("mode") != "subscription" or not paid or not session.get("subscription"):
            raise IgnoredEvent
        subscription_id = _id(session["subscription"])
        invoice = session.get("invoice")
        if not isinstance(invoice, dict) and invoice:
            invoice = self._stripe.v1.invoices.retrieve(invoice).to_dict()
        return self._from_subscription(data, subscription_id, _charge(invoice))

    def _invoice_paid(self, data: dict) -> ProviderEvent:
        invoice = data["data"]["object"]
        subscription_id, _ = _invoice_subscription(invoice)
        if subscription_id is None:
            raise IgnoredEvent  # not a subscription's invoice
        charge = _charge(invoice)
        reason = invoice.get("billing_reason")
        if reason in ("subscription_create", "subscription_cycle"):
            # The first payment, or a renewal: with the period it pays for.
            return self._from_subscription(data, subscription_id, charge)
        return self._event(
            data,
            type="payment_succeeded",
            subscription_id=subscription_id,
            customer_id=_id(invoice.get("customer")),
            charge=charge,
        )

    def _invoice_failed(self, data: dict) -> ProviderEvent:
        invoice = data["data"]["object"]
        subscription_id, _ = _invoice_subscription(invoice)
        if subscription_id is None:
            raise IgnoredEvent
        return self._event(
            data,
            type="payment_failed",
            subscription_id=subscription_id,
            customer_id=_id(invoice.get("customer")),
            charge=_charge(invoice, failed=True),
        )

    def _subscription_updated(self, data: dict) -> ProviderEvent:
        """A changed payment method (the Customer Portal), or else the period as it stands:
        billing renews only when the period has moved on, so other changes do nothing."""
        subscription = data["data"]["object"]
        previous = data["data"].get("previous_attributes") or {}
        method = subscription.get("default_payment_method")
        if "default_payment_method" in previous and method:
            if not isinstance(method, dict):
                method = self._stripe.v1.payment_methods.retrieve(method).to_dict()
            return self._event(
                data,
                type="payment_method_updated",
                subscription_id=subscription["id"],
                customer_id=_id(subscription.get("customer")),
                payment_method=_payment_method(method),
            )
        start, end = _period(subscription)
        if end is None:
            raise IgnoredEvent
        return self._event(
            data,
            type="subscription_renewed",
            subscription_id=subscription["id"],
            customer_id=_id(subscription.get("customer")),
            period_start=start,
            period_end=end,
        )

    def _subscription_deleted(self, data: dict) -> ProviderEvent:
        subscription = data["data"]["object"]
        return self._event(
            data,
            type="subscription_ended",
            subscription_id=subscription["id"],
            customer_id=_id(subscription.get("customer")),
        )

    _EVENTS = {
        "checkout.session.completed": _checkout_completed,
        "invoice.paid": _invoice_paid,
        "invoice.payment_failed": _invoice_failed,
        "customer.subscription.updated": _subscription_updated,
        "customer.subscription.deleted": _subscription_deleted,
    }
