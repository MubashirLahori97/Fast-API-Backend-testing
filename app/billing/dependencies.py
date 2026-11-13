from typing import Annotated

from fastapi import Depends

from app.billing.fake import FakePaymentProvider
from app.billing.provider import PaymentProvider
from app.billing.stripe_provider import StripeProvider
from app.core.config import settings


def get_payment_provider() -> PaymentProvider:
    """FastAPI dependency, also called by the billing jobs and the purge. Stripe when its secret
    key is set (docs/decisions/stripe-billing.md); otherwise the fake, in development and test
    only."""
    if settings.stripe_secret_key:
        if settings.environment == "production" and not settings.stripe_webhook_secret:
            # Without it no webhook can be checked, so no payment would ever be recorded.
            raise RuntimeError("STRIPE_WEBHOOK_SECRET must be set in production.")
        return StripeProvider()
    if settings.environment == "production":
        # The fake would give real clients a paid plan without taking any payment.
        raise RuntimeError("STRIPE_SECRET_KEY must be set in production.")
    return FakePaymentProvider()


PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]
