from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.accounts.dependencies import ClientSession, consented_session
from app.billing import service
from app.billing.dependencies import PaymentProviderDep
from app.billing.schemas import (
    AddOns,
    BillingHistoryOut,
    ChangePlan,
    PaymentMethodLink,
    PlansOut,
    StartSubscription,
    SubscriptionOut,
    SubscriptionResult,
    WebhookReceived,
)
from app.core.database import DbSession
from app.core.email import EmailLater

# The client's screens: signed in, behind the policy gate. A client whose trial or plan has
# ended can still open them, to subscribe (9.1).
router = APIRouter(prefix="/billing", tags=["billing"], dependencies=[Depends(consented_session)])
# The payment provider's events: no sign-in, a signature instead.
webhook_router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans")
def get_plans(session: ClientSession) -> PlansOut:
    """Story 9.1's plan screen: both plans with their prices and what's included, the add-on
    price and the renewal disclaimer."""
    return service.plans(session.user)


@router.get("/subscription")
def get_subscription(session: ClientSession, db: DbSession) -> SubscriptionOut:
    """Story 11.3's current plan: plan, status, next billing date and amount, family places,
    payment method, and the texts to confirm before cancelling or downgrading."""
    return service.subscription_out(db, session.user)


@router.post("/subscription")
def start_subscription(
    body: StartSubscription,
    session: ClientSession,
    provider: PaymentProviderDep,
    send: EmailLater,
    request: Request,
    db: DbSession,
) -> SubscriptionResult:
    """Story 9.1's Subscribe, from the trial, after it, or after a subscription ended. While a
    cancelled subscription still has access, it resumes instead (11.3)."""
    return service.start(db, provider, send, session.user, body, request)


@router.post("/subscription/plan")
def change_plan(
    body: ChangePlan,
    session: ClientSession,
    provider: PaymentProviderDep,
    send: EmailLater,
    request: Request,
    db: DbSession,
) -> SubscriptionResult:
    """Story 11.3: Individual to Family at once; Family to Individual from the next billing
    date (show `downgrade_confirmation` from GET /billing/subscription first)."""
    return service.change_plan(db, provider, send, session.user, body, request)


@router.post("/subscription/add-ons")
def add_add_ons(
    body: AddOns,
    session: ClientSession,
    provider: PaymentProviderDep,
    send: EmailLater,
    request: Request,
    db: DbSession,
) -> SubscriptionResult:
    """Story 9.1's add-on, after the client confirms "Adding [Name] will add [price] a month".
    Then the app adds or turns on the member again."""
    return service.add_add_ons(db, provider, send, session.user, body, request)


@router.post("/subscription/cancel")
def cancel_subscription(
    session: ClientSession, provider: PaymentProviderDep, request: Request, db: DbSession
) -> SubscriptionResult:
    """Story 11.3 (show `cancel_confirmation` first). Access continues until the end of the
    period."""
    return service.cancel(db, provider, session.user, request)


@router.post("/subscription/resume")
def resume_subscription(
    session: ClientSession, provider: PaymentProviderDep, request: Request, db: DbSession
) -> SubscriptionResult:
    """Undoes a cancellation before the period ends."""
    return service.resume(db, provider, session.user, request)


@router.post("/payment-method")
def change_payment_method(
    session: ClientSession, provider: PaymentProviderDep, request: Request, db: DbSession
) -> PaymentMethodLink:
    """Story 11.3's Change: a link to the provider's page."""
    return service.payment_method_link(db, provider, session.user, request)


@router.get("/invoices")
def billing_history(session: ClientSession, db: DbSession) -> BillingHistoryOut:
    """Story 11.3's billing history, newest first."""
    return service.history(db, session.user)


async def _raw_body(request: Request) -> bytes:
    """The body exactly as sent: the signature is over these bytes."""
    return await request.body()


@webhook_router.post("/webhook")
def payment_webhook(
    body: Annotated[bytes, Depends(_raw_body)],
    request: Request,
    provider: PaymentProviderDep,
    send: EmailLater,
    db: DbSession,
) -> WebhookReceived:
    """The payment provider's events: payments, failed payments, renewals and endings. Each
    is handled once, however often it's delivered."""
    service.handle_webhook(db, provider, send, body, request.headers)
    return WebhookReceived()
