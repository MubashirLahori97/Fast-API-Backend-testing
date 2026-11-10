from typing import Annotated

from fastapi import Depends

from app.billing.fake import FakePaymentProvider
from app.billing.provider import PaymentProvider
from app.core.config import settings


def get_payment_provider() -> PaymentProvider:
    """FastAPI dependency, also called by the billing jobs. Return the real provider here once
    question 2 is decided (docs/PLAN.md); its webhook secret must not be the development
    default."""
    if settings.environment == "production":
        # The fake would give real clients a paid plan without taking any payment.
        raise RuntimeError("No payment provider is configured for production.")
    return FakePaymentProvider()


PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]
