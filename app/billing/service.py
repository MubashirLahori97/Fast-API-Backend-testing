"""Subscriptions, add-ons and payments (stories 9.1 and 11.3).

- **Client actions** (subscribe, change plan, add-ons, cancel, resume) take the account row lock
  and then the subscription's, so two taps can't subscribe twice. Each one checks the request,
  calls the payment provider, and only then saves what the provider did.
- **The provider's webhooks** (handle_webhook) record payments, renewals, failed payments and
  endings. Each event is handled once, in one transaction with its PaymentEvent row.
- **Changes that come with time** are made by CHECK_JOB, queued for the moment they're due: the
  end of a cancelled period or of a grace period, and the next billing date's downgrade and
  add-on changes. entitlements.py checks the same times, so access never outlasts them, even if
  the worker is late.
- **Family members** follow the Family plan through family.py's job.

`users.subscription_plan` is kept in step (_mirror_plan): the plan the account can use now, or
null. Subscription and payment events go in the audit log, with no card details.
"""

import logging
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.billing import catalog, emails, entitlements, family
from app.billing.catalog import PaidPlan
from app.billing.emails import long_date
from app.billing.models import Invoice, PaymentEvent, Subscription
from app.billing.provider import (
    STORES,
    Charge,
    CheckoutRequest,
    IgnoredEvent,
    InvalidEvent,
    InvalidSignature,
    PaymentCancelled,
    PaymentDeclined,
    PaymentMethod,
    PaymentProvider,
    ProviderError,
    ProviderEvent,
    Started,
)
from app.billing.schemas import (
    AddOns,
    BillingHistoryOut,
    ChangePlan,
    InvoiceOut,
    PaymentMethodLink,
    PaymentMethodOut,
    PlanOut,
    PlansOut,
    Price,
    StartSubscription,
    Status,
    SubscriptionOut,
    SubscriptionResult,
)
from app.core import audit, jobs
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import ACTION_FAILED, AppError, database_errors_retryable
from app.notifications import service as notifications
from app.profiles.models import Profile

logger = logging.getLogger(__name__)

CHECK_JOB = "billing.check_subscription"  # see app/billing/jobs.py

# Story 9.1's messages.
SUBSCRIPTION_ACTIVE = "You’re all set. Welcome to the {plan} plan."
PAYMENT_FAILED = (
    "We couldn’t process your payment. Please check your details or try another way to pay."
)
PAYMENT_CANCELLED = "Your payment was cancelled. You can subscribe whenever you’re ready."
FAMILY_FOR_ADD_ONS = "Adding family members is part of the Family plan. Upgrade to add someone."
ADD_ON_CONFIRMATION = "Adding [Name] will add {price} a month to your subscription. Continue?"
# Story 11.3's messages.
CANCEL_CONFIRMATION = (
    "Cancel your subscription? You’ll keep access until {date}. After that, you won’t be able "
    "to talk with me or see your Wellness Plan until you subscribe again."
)
SUBSCRIPTION_CANCELLED = "Your subscription has been cancelled. You have access until {date}."
DOWNGRADE_CONFIRMATION = (
    "Moving to the {plan} plan will turn off your family members’ profiles from {date}. Their "
    "information will be kept, and you can turn them back on by returning to the Family plan. "
    "Do you want to continue?"
)
RENEWAL_FAILED = (
    "We couldn’t renew your subscription. Please update your payment method to keep your access."
)
MANAGED_BY_STORE = "You subscribed through {store}. Please manage your subscription there."
CHOOSE_MEMBERS = (
    "Your plan includes {count} family {members}. Choose who to turn back on, or add another "
    "member."
)
NO_BILLING_HISTORY = "There’s no billing history yet."
# Not in the stories (docs/decisions/phase-8-billing.md).
ALREADY_SUBSCRIBED = "You’re already on the {plan} plan."
PRICE_CHANGED = "The price has changed. Please check the new price and try again."
NO_SUBSCRIPTION = "You don’t have an active subscription. Choose a plan to subscribe."
CANCELLED_RESUME_FIRST = "Your subscription has been cancelled. Resume it first to make changes."
NOT_CANCELLED = "Your subscription is already active."
RESUMED = "Your subscription will continue. It renews on {date}."
DOWNGRADE_SCHEDULED = "You’ll move to the {plan} plan on {date}."
STAYING_ON_FAMILY = "You’ll stay on the {plan} plan."
OWN_PROFILE_REQUIRED = (
    "The {plan} plan covers your own profile only. Please set up your own profile first, or "
    "choose the {family} plan."
)
TEEN_ACCOUNT = "Your access comes through your parent’s or guardian’s Family plan."
TOO_MANY_ADD_ONS = "You can add up to {count} extra family members."
# The Super Admin made the plan inactive (Super Admin 8.1): clients already on it keep it.
PLAN_UNAVAILABLE = "That plan isn’t available any more. Please choose another plan."
# For the provider, never shown in the apps.
INVALID_SIGNATURE = "The webhook signature isn’t valid."
INVALID_EVENT = "The webhook event couldn’t be read."


def _now() -> datetime:
    return datetime.now(UTC)


def _price(cents: int) -> Price:
    return Price(
        amount_cents=cents, currency=settings.billing_currency, display=catalog.format_price(cents)
    )


def _name(plan: str) -> str:
    return catalog.plan_name(plan)


# Checks


def _check_client(account: User) -> None:
    """Stories 9.1 and 11.3: a teen with their own account has no billing; their access comes
    through the parent's Family plan (1.5). That includes a teen who has reached adult age but
    hasn't created their adult account yet (1.6): plans come after Create My Account."""
    if account.account_type == "teen":
        raise AppError(403, "teen_account", TEEN_ACCOUNT)


def _check_managed_here(sub: Subscription) -> None:
    """11.3: a subscription bought through Apple or Google is managed in their store."""
    if sub.provider in STORES:
        raise AppError(409, "managed_by_store", MANAGED_BY_STORE.format(store=STORES[sub.provider]))


def _check_price(confirmed: int | None, expected: int) -> None:
    """9.1: the client confirms the price they were shown. If the admin team changed it since,
    they see the new one before paying it."""
    if confirmed != expected:
        raise AppError(409, "price_changed", PRICE_CHANGED, "confirmed_monthly_price_cents")


def _check_individual_allowed(db: Session, account: User, plan: PaidPlan) -> None:
    """The Individual plan is the client's own profile only (9.1). An advocate-only client (no
    own profile, family members only) would be left with nobody to talk about, so they're
    asked to set up their own profile first (docs/decisions/phase-8-billing.md)."""
    if plan != "individual":
        return
    own = db.scalar(
        select(Profile.id).where(Profile.account_id == account.id, Profile.is_self.is_(True))
    )
    if own is not None:
        return
    family_member = db.scalar(
        select(Profile.id)
        .where(
            Profile.account_id == account.id,
            Profile.intake_completed_at.is_not(None),
            Profile.deletion_requested_at.is_(None),
        )
        .limit(1)
    )
    if family_member is not None:
        raise AppError(
            409,
            "own_profile_required",
            OWN_PROFILE_REQUIRED.format(plan=_name("individual"), family=_name("family")),
        )


def _check_available(plan: PaidPlan, current: Subscription | None) -> None:
    """New subscribers can't choose an inactive plan; a client already on it keeps it."""
    staying = current is not None and entitlements.gives_access(current) and current.plan == plan
    if not staying and not catalog.is_available(plan):
        raise AppError(409, "plan_unavailable", PLAN_UNAVAILABLE, "plan")


def _check_has_subscription(sub: Subscription | None) -> Subscription:
    if sub is None or not entitlements.gives_access(sub):
        raise AppError(409, "no_subscription", NO_SUBSCRIPTION)
    _check_managed_here(sub)
    return sub


# Saving


def _lock(db: Session, account: User) -> Subscription | None:
    """The account row lock, then the subscription's. Every billing change takes them in this
    order; 8.2's actions take a family member's lock and then the account's, and billing never
    locks a profile, so the two can't deadlock."""
    db.refresh(account, with_for_update=True)
    return db.scalar(
        select(Subscription)
        .where(Subscription.account_id == account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_account_id(db: Session, account_id: uuid.UUID) -> tuple[User | None, Subscription | None]:
    account = db.get(User, account_id, with_for_update=True, populate_existing=True)
    if account is None:
        return None, None
    return account, _lock(db, account)


def _mirror_plan(account: User, sub: Subscription) -> None:
    """users.subscription_plan: the plan the account can use now, or null (the trial reminders
    filter on it)."""
    account.subscription_plan = sub.plan if entitlements.gives_access(sub) else None


def _schedule_check(db: Session, sub: Subscription, at: datetime | None) -> None:
    """Queues CHECK_JOB for when something is due. Extra or early runs change nothing."""
    if at is not None:
        jobs.enqueue(db, CHECK_JOB, {"subscription_id": str(sub.id)}, run_at=at)


def _schedule_period_end(db: Session, sub: Subscription) -> None:
    """CHECK_JOB at the next billing date, and shortly before it, when add-ons no longer used
    are taken off the provider's subscription so its renewal invoice doesn't charge them
    (11.3)."""
    lead = timedelta(minutes=settings.billing_pre_renewal_minutes)
    _schedule_check(db, sub, sub.current_period_end - lead)
    _schedule_check(db, sub, sub.current_period_end)


def _audit(
    db: Session,
    action: str,
    account: User,
    sub: Subscription,
    *,
    request: Request | None = None,
    by_client: bool = False,
    details: dict | None = None,
) -> None:
    """A billing event. Those the provider or the worker cause have no actor, and name the
    account in the details."""
    audit.record(
        db,
        action,
        actor_id=account.id if by_client else None,
        target_type="subscription",
        target_id=sub.id,
        request=request,
        details={**({} if by_client else {"account_id": str(account.id)}), **(details or {})},
    )


def _set_payment_method(sub: Subscription, method: PaymentMethod | None) -> None:
    if method is not None:
        sub.payment_method_brand = method.brand
        sub.payment_method_last4 = method.last4


def _record_charge(
    db: Session,
    account: User,
    provider_name: str,
    charge: Charge,
    status: str,
    plan: str | None,
) -> Invoice | None:
    """Adds or updates the invoice. Returns it when it has just been paid, for the receipt."""
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.provider == provider_name, Invoice.provider_invoice_id == charge.invoice_id)
        .with_for_update()
    )
    if invoice is None:
        invoice = Invoice(
            account_id=account.id,
            provider=provider_name,
            provider_invoice_id=charge.invoice_id,
            plan=plan,
        )
        db.add(invoice)
    elif invoice.status == "paid":
        return None  # told twice
    invoice.amount_cents = charge.amount_cents
    invoice.currency = charge.currency
    invoice.status = status
    invoice.issued_at = charge.at
    invoice.receipt_url = charge.receipt_url or invoice.receipt_url
    db.flush()
    return invoice if status == "paid" else None


def _send_receipts(send: SendEmail, receipts: list[tuple[User, Invoice | None]]) -> None:
    """After the commit, so a receipt only goes out for a payment that was saved."""
    if not settings.send_receipt_emails:
        return
    for account, invoice in receipts:
        if invoice is not None:
            send(emails.receipt(account.email, invoice))


@contextmanager
def _provider_call(db: Session, account: User, action: str, request: Request | None) -> Iterator:
    """Turns the provider's failures into the stories' messages. Nothing has been changed when
    the provider is called, so a declined or cancelled payment only adds an audit event."""
    try:
        yield
    except (PaymentDeclined, PaymentCancelled) as error:
        declined = isinstance(error, PaymentDeclined)
        audit.record(
            db,
            "billing.payment.declined" if declined else "billing.payment.cancelled",
            actor_id=account.id,
            request=request,
            details={"action": action},
        )
        db.commit()
        if declined:
            raise AppError(402, "payment_failed", PAYMENT_FAILED) from None
        raise AppError(409, "payment_cancelled", PAYMENT_CANCELLED) from None
    except ProviderError as error:
        logger.warning("Payment provider call failed (%s): %s", action, type(error).__name__)
        raise AppError(503, "provider_unavailable", ACTION_FAILED) from None


def _activate(
    db: Session,
    account: User,
    sub: Subscription | None,
    provider_name: str,
    plan: PaidPlan,
    add_on_members: int,
    started: Started,
    request: Request | None = None,
    by_client: bool = False,
) -> tuple[Subscription, Invoice | None]:
    """9.1: once the first payment succeeds, the subscription is active straight away and the
    plan's features unlock. Trial history isn't touched, so it's all kept."""
    if sub is None:
        sub = Subscription(id=uuid.uuid4(), account_id=account.id)
        db.add(sub)
    sub.provider = provider_name
    sub.provider_customer_id = started.customer_id
    sub.provider_subscription_id = started.subscription_id
    sub.plan = plan
    sub.status = "active"
    sub.plan_price_cents = catalog.offer(plan).monthly_price_cents
    sub.add_on_price_cents = catalog.add_on_price_cents()
    sub.currency = settings.billing_currency
    sub.add_on_members = add_on_members if plan == "family" else 0
    sub.pending_plan = None
    sub.current_period_start = started.period_start
    sub.current_period_end = started.period_end
    sub.settled_period_end = None
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.grace_ends_at = None
    sub.ended_at = None
    sub.ended_reason = None
    sub.started_at = _now()
    _set_payment_method(sub, started.payment_method)
    db.flush()
    invoice = _record_charge(db, account, provider_name, started.charge, "paid", plan)
    _mirror_plan(account, sub)
    _audit(
        db,
        "billing.subscription.started",
        account,
        sub,
        request=request,
        by_client=by_client,
        details={"plan": plan, "add_on_members": sub.add_on_members, "provider": provider_name},
    )
    _schedule_period_end(db, sub)
    family.queue_sync(db, account)  # family members turned off by an earlier end come back
    return sub, invoice


def _add_ons_needed(db: Session, account: User) -> int:
    used = entitlements.family_members_used(db, account)
    return max(0, used - catalog.family_members_included())


def _settle_period(
    db: Session, provider: PaymentProvider, account: User, sub: Subscription
) -> None:
    """At the next billing date (11.3): a downgrade to Individual applies, and add-ons the
    client no longer uses (they turned off or removed a member) stop. Done once per period,
    by CHECK_JOB at the period end or by the renewal event, whichever comes first."""
    if sub.settled_period_end == sub.current_period_end:
        return
    sub.settled_period_end = sub.current_period_end
    if sub.pending_plan is not None and sub.pending_plan != sub.plan:
        old = sub.plan
        sub.plan = sub.pending_plan
        sub.plan_price_cents = catalog.offer(sub.plan).monthly_price_cents
        _audit(db, "billing.subscription.plan_changed", account, sub, details={"from": old})
        family.queue_sync(db, account)
    sub.pending_plan = None
    if sub.plan != "family":
        sub.add_on_members = 0
        return
    needed = _add_ons_needed(db, account)
    if needed < sub.add_on_members:
        if sub.provider == provider.name:
            provider.set_add_on_members(
                sub.provider_subscription_id,
                needed,
                price_cents=sub.add_on_price_cents,
                prorate=False,
            )
        _audit(
            db,
            "billing.add_ons.released",
            account,
            sub,
            details={"from": sub.add_on_members, "to": needed},
        )
        sub.add_on_members = needed


def _renew(
    db: Session,
    provider: PaymentProvider,
    account: User,
    sub: Subscription,
    start: datetime | None,
    end: datetime,
) -> None:
    """A new billing period. Prices changed in the admin panel apply from here (Super Admin
    8.1)."""
    _settle_period(db, provider, account, sub)
    sub.current_period_start = start or sub.current_period_end
    sub.current_period_end = end
    if sub.status == "cancelled":
        # The provider renewed it, so it wasn't cancelled there after all.
        sub.status = "past_due" if sub.grace_ends_at else "active"
        sub.cancel_at_period_end = False
        sub.cancelled_at = None
    sub.plan_price_cents = catalog.offer(sub.plan).monthly_price_cents
    sub.add_on_price_cents = catalog.add_on_price_cents()
    _audit(db, "billing.subscription.renewed", account, sub, details={"plan": sub.plan})
    _schedule_period_end(db, sub)


def _end(db: Session, account: User, sub: Subscription, reason: str) -> None:
    """11.3: access stops ("the locked state, as when a trial ends"), add-ons end with it, and
    family members are turned off. Nothing else is deleted."""
    sub.status = "ended"
    sub.ended_at = _now()
    sub.ended_reason = reason
    sub.add_on_members = 0
    sub.pending_plan = None
    sub.grace_ends_at = None
    _mirror_plan(account, sub)
    _audit(
        db, "billing.subscription.ended", account, sub, details={"reason": reason, "plan": sub.plan}
    )
    family.queue_sync(db, account)


# Screens


def plans(account: User) -> PlansOut:
    """Story 9.1's plan screen."""
    _check_client(account)
    add_on = catalog.add_on_price_cents()
    return PlansOut(
        plans=[
            PlanOut(
                code=offer.plan,
                name=offer.name,
                monthly_price=_price(offer.monthly_price_cents),
                family_members_included=offer.family_members_included,
                features=list(offer.features),
            )
            for offer in catalog.offers()
        ],
        add_on_monthly_price=_price(add_on),
        renewal_disclaimer=catalog.RENEWAL_DISCLAIMER,
        add_on_confirmation=ADD_ON_CONFIRMATION.format(price=catalog.format_price(add_on)),
        trial_days=catalog.trial_days(),
    )


def _next_amount(db: Session, account: User, sub: Subscription) -> int:
    """What the next billing date will charge: the plan it'll be on, and the add-ons still in
    use (11.3: a removed add-on member stops being charged from the next billing date)."""
    plan = sub.pending_plan or sub.plan
    if plan == sub.plan:
        amount = sub.plan_price_cents
    else:
        amount = catalog.offer(plan).monthly_price_cents
    if plan == "family":
        amount += min(sub.add_on_members, _add_ons_needed(db, account)) * sub.add_on_price_cents
    return amount


def subscription_out(db: Session, account: User) -> SubscriptionOut:
    """Story 11.3's current plan."""
    _check_client(account)
    sub = entitlements.subscription(account)
    access = entitlements.gives_access(sub)
    status: Status
    if sub is None:
        status, plan = "trial", "trial"
    elif not access:
        status, plan = "ended", sub.plan
    else:
        status = {"active": "active", "past_due": "payment_issue"}.get(sub.status, "cancelled")
        plan = sub.plan
    until = entitlements.access_until(sub) if sub is not None and access else None
    renews = access and sub.status in ("active", "past_due")
    managed_here = sub is not None and sub.provider not in STORES

    message = None
    if status == "trial" and entitlements.trial_ended(account):
        message = entitlements.TRIAL_ENDED
    elif status == "ended":
        message = entitlements.SUBSCRIPTION_ENDED
    elif status == "payment_issue":
        message = RENEWAL_FAILED
    elif status == "cancelled":
        message = SUBSCRIPTION_CANCELLED.format(date=long_date(until))

    is_family = access and plan == "family"
    used = entitlements.family_members_used(db, account) if is_family else None
    included = entitlements.family_members_included(account) if is_family else None
    waiting = len(family.waiting(db, account))
    choose = None
    if is_family and waiting > included - used:
        choose = CHOOSE_MEMBERS.format(
            count=included, members="member" if included == 1 else "members"
        )

    cancel_confirmation = downgrade_confirmation = None
    if renews and managed_here:
        cancel_at = max(sub.current_period_end, sub.grace_ends_at or sub.current_period_end)
        cancel_confirmation = CANCEL_CONFIRMATION.format(date=long_date(cancel_at))
        if plan == "family" and sub.status == "active" and sub.pending_plan is None:
            downgrade_confirmation = DOWNGRADE_CONFIRMATION.format(
                plan=_name("individual"), date=long_date(sub.current_period_end)
            )

    return SubscriptionOut(
        plan=plan,
        plan_name=_name(plan),
        status=status,
        has_access=not entitlements.trial_ended(account),
        trial_ends_at=account.trial_ends_at,
        trial_days_left=entitlements.trial_days_left(account),
        access_until=until,
        next_billing_at=sub.current_period_end if renews else None,
        next_billing_amount=_price(_next_amount(db, account, sub)) if renews else None,
        scheduled_plan=sub.pending_plan if access and sub.pending_plan != sub.plan else None,
        family_members_used=used,
        family_members_included=included,
        add_on_members=sub.add_on_members if access else 0,
        add_on_monthly_price=_price(sub.add_on_price_cents) if is_family else None,
        payment_method=(
            PaymentMethodOut(brand=sub.payment_method_brand, last4=sub.payment_method_last4)
            if sub is not None and sub.payment_method_brand and access
            else None
        ),
        managed_by=(sub.provider if sub.provider in STORES else "app") if sub else None,
        renewal_disclaimer=catalog.RENEWAL_DISCLAIMER_SHORT if renews else None,
        message=message,
        cancel_confirmation=cancel_confirmation,
        downgrade_confirmation=downgrade_confirmation,
        family_members_waiting=waiting,
        choose_family_members=choose,
        locked_features=[
            feature for feature, locked in entitlements.feature_access(account).items() if locked
        ],
    )


def _result(
    db: Session, account: User, message: str | None, checkout_url: str | None = None
) -> SubscriptionResult:
    return SubscriptionResult(
        message=message, checkout_url=checkout_url, subscription=subscription_out(db, account)
    )


def history(db: Session, account: User) -> BillingHistoryOut:
    """11.3's billing history: each payment's date, amount and status, with its receipt."""
    _check_client(account)
    sub = entitlements.subscription(account)
    if sub is not None and sub.provider in STORES:
        # 11.3: for Apple and Google subscriptions, the history is kept in the store.
        return BillingHistoryOut(
            invoices=[], message=MANAGED_BY_STORE.format(store=STORES[sub.provider])
        )
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.account_id == account.id)
        .order_by(Invoice.issued_at.desc(), Invoice.created_at.desc())
    ).all()
    return BillingHistoryOut(
        invoices=[
            InvoiceOut(
                id=invoice.id,
                issued_at=invoice.issued_at,
                amount=_price(invoice.amount_cents),
                status=invoice.status,
                plan=invoice.plan,
                receipt_url=invoice.receipt_url,
            )
            for invoice in invoices
        ],
        message=None if invoices else NO_BILLING_HISTORY,
    )


# Client actions


def start(
    db: Session,
    provider: PaymentProvider,
    send: SendEmail,
    account: User,
    body: StartSubscription,
    request: Request,
) -> SubscriptionResult:
    """9.1's Subscribe. A provider with a hosted page answers with checkout_url, and the
    subscription starts when its payment_succeeded event arrives; the fake pays at once."""
    _check_client(account)
    plan = body.plan
    if plan != "family" and body.add_on_members:
        raise AppError(422, "family_plan_required", FAMILY_FOR_ADD_ONS, "add_on_members")
    receipts: list[tuple[User, Invoice | None]] = []
    with database_errors_retryable(db):
        sub = _lock(db, account)
        _check_available(plan, sub)
        if sub is not None and entitlements.gives_access(sub):
            _check_managed_here(sub)
            if sub.status != "cancelled":
                raise AppError(
                    409, "already_subscribed", ALREADY_SUBSCRIBED.format(plan=_name(sub.plan))
                )
            # 11.3: cancelled, then subscribing again before the period ends: the
            # subscription continues without a break. A different plan is checked first, and
            # the resume is saved before the plan changes, so a refused change leaves the
            # subscription resumed here as it is at the provider.
            if plan == "family" and sub.plan != "family":
                _check_price(
                    body.confirmed_monthly_price_cents, catalog.monthly_total_cents("family")
                )
            if plan != sub.plan:
                _check_individual_allowed(db, account, plan)
            message = _resume_locked(db, provider, account, sub, request)
            db.commit()
            if plan != sub.plan:
                sub = _lock(db, account)
                message, invoice = _change_plan_locked(
                    db, provider, account, sub, plan, body.confirmed_monthly_price_cents, request
                )
                receipts.append((account, invoice))
                db.commit()
            _send_receipts(send, receipts)
            return _result(db, account, message)

        _check_individual_allowed(db, account, plan)
        _check_price(
            body.confirmed_monthly_price_cents,
            catalog.monthly_total_cents(plan, body.add_on_members),
        )
        checkout_request = CheckoutRequest(
            account_id=account.id,
            email=account.email,
            customer_id=sub.provider_customer_id if sub is not None else None,
            plan=plan,
            add_on_members=body.add_on_members,
            plan_price_cents=catalog.offer(plan).monthly_price_cents,
            add_on_price_cents=catalog.add_on_price_cents(),
            currency=settings.billing_currency,
            return_url=settings.billing_return_url,
        )
        with _provider_call(db, account, "subscribe", request):
            checkout = provider.start_checkout(checkout_request)
        if checkout.started is None:
            audit.record(
                db,
                "billing.checkout.started",
                actor_id=account.id,
                request=request,
                details={"plan": plan, "add_on_members": body.add_on_members},
            )
            db.commit()
            return _result(db, account, None, checkout_url=checkout.url)
        sub, invoice = _activate(
            db,
            account,
            sub,
            provider.name,
            plan,
            body.add_on_members,
            checkout.started,
            request=request,
            by_client=True,
        )
        receipts.append((account, invoice))
        db.commit()
    _send_receipts(send, receipts)
    return _result(db, account, SUBSCRIPTION_ACTIVE.format(plan=_name(plan)))


def _resume_locked(
    db: Session, provider: PaymentProvider, account: User, sub: Subscription, request: Request
) -> str:
    with _provider_call(db, account, "resume", request):
        provider.resume(sub.provider_subscription_id)
    sub.status = "past_due" if sub.grace_ends_at else "active"
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    _mirror_plan(account, sub)
    _audit(db, "billing.subscription.resumed", account, sub, request=request, by_client=True)
    _schedule_check(db, sub, sub.grace_ends_at or sub.current_period_end)
    if sub.status == "past_due":
        return RENEWAL_FAILED
    return RESUMED.format(date=long_date(sub.current_period_end))


def _change_plan_locked(
    db: Session,
    provider: PaymentProvider,
    account: User,
    sub: Subscription,
    plan: PaidPlan,
    confirmed_price: int | None,
    request: Request,
) -> tuple[str, Invoice | None]:
    """11.3: Individual to Family applies at once, once it's paid; Family to Individual from the
    next billing date. Choosing Family while a downgrade is waiting keeps the Family plan."""
    _check_available(plan, sub)
    if plan == "family":
        if sub.plan == "family":
            if sub.pending_plan is None:
                raise AppError(
                    409, "already_subscribed", ALREADY_SUBSCRIBED.format(plan=_name("family"))
                )
            with _provider_call(db, account, "keep_plan", request):
                provider.change_plan(
                    sub.provider_subscription_id,
                    "family",
                    monthly_price_cents=sub.plan_price_cents,
                    at_period_end=True,
                )
            sub.pending_plan = None
            _audit(
                db,
                "billing.subscription.downgrade_cancelled",
                account,
                sub,
                request=request,
                by_client=True,
            )
            return STAYING_ON_FAMILY.format(plan=_name("family")), None
        if sub.status == "past_due":
            raise AppError(409, "payment_issue", RENEWAL_FAILED)
        price = catalog.offer("family").monthly_price_cents
        _check_price(confirmed_price, catalog.monthly_total_cents("family"))
        with _provider_call(db, account, "upgrade", request):
            charge = provider.change_plan(
                sub.provider_subscription_id,
                "family",
                monthly_price_cents=price,
                at_period_end=False,
            )
        old = sub.plan
        sub.plan = "family"
        sub.plan_price_cents = price
        sub.add_on_price_cents = catalog.add_on_price_cents()
        sub.pending_plan = None
        invoice = None
        if charge is not None:
            invoice = _record_charge(db, account, sub.provider, charge, "paid", "family")
        _mirror_plan(account, sub)
        _audit(
            db,
            "billing.subscription.upgraded",
            account,
            sub,
            request=request,
            by_client=True,
            details={"from": old},
        )
        family.queue_sync(db, account)  # family members waiting from an earlier end come back
        return SUBSCRIPTION_ACTIVE.format(plan=_name("family")), invoice

    if sub.plan == "individual":
        raise AppError(
            409, "already_subscribed", ALREADY_SUBSCRIBED.format(plan=_name("individual"))
        )
    scheduled = DOWNGRADE_SCHEDULED.format(
        plan=_name("individual"), date=long_date(sub.current_period_end)
    )
    if sub.pending_plan == "individual":
        return scheduled, None
    _check_individual_allowed(db, account, "individual")
    with _provider_call(db, account, "downgrade", request):
        provider.change_plan(
            sub.provider_subscription_id,
            "individual",
            monthly_price_cents=catalog.offer("individual").monthly_price_cents,
            at_period_end=True,
        )
    sub.pending_plan = "individual"
    _audit(
        db,
        "billing.subscription.downgrade_scheduled",
        account,
        sub,
        request=request,
        by_client=True,
    )
    _schedule_check(db, sub, sub.current_period_end)
    return scheduled, None


def change_plan(
    db: Session,
    provider: PaymentProvider,
    send: SendEmail,
    account: User,
    body: ChangePlan,
    request: Request,
) -> SubscriptionResult:
    _check_client(account)
    with database_errors_retryable(db):
        sub = _check_has_subscription(_lock(db, account))
        if sub.status == "cancelled":
            raise AppError(409, "subscription_cancelled", CANCELLED_RESUME_FIRST)
        message, invoice = _change_plan_locked(
            db, provider, account, sub, body.plan, body.confirmed_monthly_price_cents, request
        )
        db.commit()
    _send_receipts(send, [(account, invoice)])
    return _result(db, account, message)


def add_add_ons(
    db: Session,
    provider: PaymentProvider,
    send: SendEmail,
    account: User,
    body: AddOns,
    request: Request,
) -> SubscriptionResult:
    """9.1's add-on: the client confirmed "Adding [Name] will add [price] a month...", and the
    places are added to the subscription, charged from today. The app then adds or turns on
    the member again (8.1, 8.2), which now finds a free place."""
    _check_client(account)
    with database_errors_retryable(db):
        sub = _lock(db, account)
        if sub is None or not entitlements.gives_access(sub) or sub.plan != "family":
            raise AppError(403, "family_plan_required", FAMILY_FOR_ADD_ONS)
        _check_managed_here(sub)
        if sub.status == "cancelled":
            raise AppError(409, "subscription_cancelled", CANCELLED_RESUME_FIRST)
        if sub.status == "past_due":
            raise AppError(409, "payment_issue", RENEWAL_FAILED)
        count = sub.add_on_members + body.count
        if count > settings.max_add_on_members:
            message = TOO_MANY_ADD_ONS.format(count=settings.max_add_on_members)
            raise AppError(422, "too_many_add_ons", message, "count")
        price = catalog.add_on_price_cents()
        _check_price(body.confirmed_monthly_price_cents, price * body.count)
        with _provider_call(db, account, "add_ons", request):
            charge = provider.set_add_on_members(
                sub.provider_subscription_id, count, price_cents=price, prorate=True
            )
        sub.add_on_members = count
        sub.add_on_price_cents = price
        invoice = None
        if charge is not None:
            invoice = _record_charge(db, account, sub.provider, charge, "paid", "family")
        _audit(
            db,
            "billing.add_ons.added",
            account,
            sub,
            request=request,
            by_client=True,
            details={"added": body.count, "add_on_members": count},
        )
        family.queue_sync(db, account)  # members waiting to come back may all fit now
        db.commit()
    _send_receipts(send, [(account, invoice)])
    return _result(db, account, None)


def cancel(
    db: Session, provider: PaymentProvider, account: User, request: Request
) -> SubscriptionResult:
    """11.3: access continues until the end of the period paid for; nothing is deleted.
    Cancelling again changes nothing."""
    _check_client(account)
    with database_errors_retryable(db):
        sub = _check_has_subscription(_lock(db, account))
        if sub.status != "cancelled":
            with _provider_call(db, account, "cancel", request):
                provider.cancel(sub.provider_subscription_id, at_period_end=True)
            sub.status = "cancelled"
            sub.cancel_at_period_end = True
            sub.cancelled_at = _now()
            _mirror_plan(account, sub)
            _audit(
                db, "billing.subscription.cancelled", account, sub, request=request, by_client=True
            )
            _schedule_check(db, sub, entitlements.access_until(sub))
            db.commit()
        until = entitlements.access_until(sub)
    return _result(db, account, SUBSCRIPTION_CANCELLED.format(date=long_date(until)))


def resume(
    db: Session, provider: PaymentProvider, account: User, request: Request
) -> SubscriptionResult:
    """Undoes a cancellation before the period ends (11.3: "continues, without a break")."""
    _check_client(account)
    with database_errors_retryable(db):
        sub = _check_has_subscription(_lock(db, account))
        if sub.status != "cancelled":
            raise AppError(409, "not_cancelled", NOT_CANCELLED)
        message = _resume_locked(db, provider, account, sub, request)
        db.commit()
    return _result(db, account, message)


def payment_method_link(
    db: Session, provider: PaymentProvider, account: User, request: Request
) -> PaymentMethodLink:
    """11.3's Change: the provider's own page, so the app never handles card details. If it
    can't be opened, the client can try again."""
    _check_client(account)
    sub = entitlements.subscription(account)
    if sub is None or sub.status == "ended" or sub.provider_customer_id is None:
        raise AppError(409, "no_subscription", NO_SUBSCRIPTION)
    _check_managed_here(sub)
    with _provider_call(db, account, "payment_method", request):
        url = provider.payment_method_link(sub.provider_customer_id, settings.billing_return_url)
    with database_errors_retryable(db):
        _audit(
            db,
            "billing.payment_method.change_started",
            account,
            sub,
            request=request,
            by_client=True,
        )
        db.commit()
    return PaymentMethodLink(url=url)


# The provider's webhooks


def _find(db: Session, provider: PaymentProvider, event: ProviderEvent) -> Subscription | None:
    return db.scalar(
        select(Subscription).where(
            Subscription.provider == provider.name,
            Subscription.provider_subscription_id == event.subscription_id,
        )
    )


def _locked_for(
    db: Session, provider: PaymentProvider, event: ProviderEvent
) -> tuple[User, Subscription] | tuple[None, None]:
    """The event's account and subscription, locked. (None, None) when the event is about a
    subscription we don't have, or one the account has since replaced."""
    found = _find(db, provider, event)
    if found is None:
        return None, None
    account, sub = _lock_account_id(db, found.account_id)
    if account is None or sub is None or sub.provider_subscription_id != event.subscription_id:
        return None, None
    return account, sub


def _start_from_checkout(
    db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list
) -> None:
    """The first payment of a hosted checkout: the subscription starts now."""
    if (
        event.account_id is None
        or event.plan is None
        or event.customer_id is None
        or event.charge is None
        or event.period_start is None
        or event.period_end is None
    ):
        logger.warning("Payment event %s is for an unknown subscription.", event.id)
        return
    account, sub = _lock_account_id(db, event.account_id)
    if account is None:
        return  # the account was deleted since
    if sub is not None and entitlements.gives_access(sub):
        # Paid twice (two checkouts): the support team refunds the second one.
        _audit(
            db,
            "billing.subscription.duplicate",
            account,
            sub,
            details={"provider_subscription_id": event.subscription_id},
        )
        return
    started = Started(
        customer_id=event.customer_id,
        subscription_id=event.subscription_id,
        period_start=event.period_start,
        period_end=event.period_end,
        charge=event.charge,
        payment_method=event.payment_method,
    )
    _, invoice = _activate(
        db, account, sub, provider.name, event.plan, event.add_on_members or 0, started
    )
    receipts.append((account, invoice))


def _on_payment_succeeded(
    db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list
) -> None:
    if _find(db, provider, event) is None:
        _start_from_checkout(db, provider, event, receipts)
        return
    account, sub = _locked_for(db, provider, event)
    if sub is None:
        return
    if event.charge is not None:
        invoice = _record_charge(db, account, provider.name, event.charge, "paid", sub.plan)
        receipts.append((account, invoice))
    _set_payment_method(sub, event.payment_method)
    if sub.status == "ended":
        _audit(db, "billing.payment.after_end", account, sub)  # for the support team
        return
    if event.period_end is not None and event.period_end > sub.current_period_end:
        _renew(db, provider, account, sub, event.period_start, event.period_end)
    if sub.grace_ends_at is not None:
        # 11.3: the payment issue is fixed, and the subscription carries on.
        sub.grace_ends_at = None
        if sub.status == "past_due":
            sub.status = "active"
        _audit(db, "billing.payment.recovered", account, sub)
    _mirror_plan(account, sub)
    amount = event.charge.amount_cents if event.charge else None
    _audit(db, "billing.payment.succeeded", account, sub, details={"amount_cents": amount})


def _on_payment_failed(
    db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list
) -> None:
    """11.3: a renewal that fails shows "Payment issue", the client is asked to update their
    payment method, and access continues for the grace period. A first payment that fails
    has no subscription yet: the client stays on the trial and can try again (9.1)."""
    account, sub = _locked_for(db, provider, event)
    if sub is None:
        return
    if event.charge is not None:
        _record_charge(db, account, provider.name, event.charge, "failed", sub.plan)
    if sub.status != "active":
        return  # already waiting for a fix, or no longer renewing
    sub.status = "past_due"
    sub.grace_ends_at = _now() + timedelta(days=settings.payment_grace_days)
    _audit(
        db,
        "billing.payment.failed",
        account,
        sub,
        details={"grace_ends_at": sub.grace_ends_at.isoformat()},
    )
    notifications.notify(db, account, "renewal_failed")
    _schedule_check(db, sub, sub.grace_ends_at)


def _on_renewed(
    db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list
) -> None:
    account, sub = _locked_for(db, provider, event)
    if sub is None or sub.status == "ended" or event.period_end is None:
        return
    if event.period_end > sub.current_period_end:
        _renew(db, provider, account, sub, event.period_start, event.period_end)


def _on_ended(db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list) -> None:
    account, sub = _locked_for(db, provider, event)
    if sub is None or sub.status == "ended":
        return
    if sub.cancel_at_period_end:
        reason = "cancelled"
    elif sub.status == "past_due":
        reason = "payment_failed"
    else:
        reason = "other"
    _end(db, account, sub, reason)


def _on_payment_method_updated(
    db: Session, provider: PaymentProvider, event: ProviderEvent, receipts: list
) -> None:
    account, sub = _locked_for(db, provider, event)
    if sub is None:
        return
    _set_payment_method(sub, event.payment_method)
    _audit(db, "billing.payment_method.updated", account, sub)


_EVENT_HANDLERS: dict[str, Callable[[Session, PaymentProvider, ProviderEvent, list], None]] = {
    "payment_succeeded": _on_payment_succeeded,
    "payment_failed": _on_payment_failed,
    "subscription_renewed": _on_renewed,
    "subscription_ended": _on_ended,
    "payment_method_updated": _on_payment_method_updated,
}


def handle_webhook(
    db: Session,
    provider: PaymentProvider,
    send: SendEmail,
    body: bytes,
    headers: Mapping[str, str],
) -> None:
    """One provider event, handled once: its PaymentEvent row is saved in the same transaction
    as what it changes. A second delivery of the same event, even at the same moment, waits
    for the first and then changes nothing. If handling fails, nothing is saved and the
    provider sends it again."""
    try:
        event = provider.parse_event(body, headers)
    except InvalidSignature:
        raise AppError(400, "invalid_signature", INVALID_SIGNATURE) from None
    except InvalidEvent:
        raise AppError(400, "invalid_event", INVALID_EVENT) from None
    except IgnoredEvent:
        return  # an event billing doesn't follow: answered 200, so it isn't sent again
    except ProviderError as error:
        # Reading the event needed the provider, which couldn't be reached: it sends it again.
        logger.warning("Payment provider call failed (webhook): %s", type(error).__name__)
        raise AppError(503, "provider_unavailable", ACTION_FAILED) from None

    receipts: list[tuple[User, Invoice | None]] = []
    with database_errors_retryable(db):
        new = db.scalar(
            insert(PaymentEvent)
            .values(id=uuid.uuid4(), provider=provider.name, event_id=event.id, type=event.type)
            .on_conflict_do_nothing(constraint="uq_payment_events_provider_event")
            .returning(PaymentEvent.id)
        )
        if new is None:
            return  # handled before
        try:
            _EVENT_HANDLERS[event.type](db, provider, event, receipts)
        except ProviderError as error:
            logger.warning("Payment provider call failed (webhook): %s", type(error).__name__)
            raise AppError(503, "provider_unavailable", ACTION_FAILED) from None
        db.commit()
    _send_receipts(send, receipts)


# Jobs


def check_subscription(db: Session, provider: PaymentProvider, subscription_id: uuid.UUID) -> None:
    """CHECK_JOB: whatever has come due. A cancelled subscription, or a failed payment not
    fixed by the end of the grace period, ends (11.3); at the period end, the downgrade and
    unused add-ons apply. The worker commits."""
    found = db.get(Subscription, subscription_id)
    if found is None:
        return
    account, sub = _lock_account_id(db, found.account_id)
    if account is None or sub is None or sub.id != subscription_id:
        return
    now = _now()
    if sub.status in ("cancelled", "past_due") and entitlements.access_until(sub) <= now:
        reason = "cancelled" if sub.status == "cancelled" else "payment_failed"
        if reason == "payment_failed" and sub.provider == provider.name:
            # The provider stops retrying. If it can't be reached, access still ends here.
            try:
                provider.cancel(sub.provider_subscription_id, at_period_end=False)
            except ProviderError as error:
                logger.warning("Couldn't cancel at the provider: %s", type(error).__name__)
        _end(db, account, sub, reason)
    elif sub.status in ("active", "past_due") and sub.current_period_end <= now:
        _settle_period(db, provider, account, sub)
    elif sub.status in ("active", "past_due") and now >= sub.current_period_end - timedelta(
        minutes=settings.billing_pre_renewal_minutes
    ):
        _release_add_ons_before_renewal(db, provider, account, sub)


def _release_add_ons_before_renewal(
    db: Session, provider: PaymentProvider, account: User, sub: Subscription
) -> None:
    """Shortly before the next billing date: add-ons the client no longer uses come off the
    provider's subscription with no proration, so the renewal invoice doesn't charge them (11.3:
    "The add-on charge stops from the next billing date"). The places stay here until the period
    ends, when _settle_period drops them. A pending downgrade took the add-ons off already."""
    if sub.plan != "family" or sub.pending_plan is not None or sub.provider != provider.name:
        return
    needed = _add_ons_needed(db, account)
    if needed < sub.add_on_members:
        provider.set_add_on_members(
            sub.provider_subscription_id, needed, price_cents=sub.add_on_price_cents, prorate=False
        )
