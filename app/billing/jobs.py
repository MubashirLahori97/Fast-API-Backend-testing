"""Background jobs for billing, run by app/worker.py. Payloads hold ids only."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.billing import family
from app.billing.dependencies import get_payment_provider
from app.billing.service import CHECK_JOB, check_subscription
from app.worker import handles


@handles(CHECK_JOB)
def run_subscription_check(db: Session, payload: dict[str, Any]) -> None:
    """The end of a cancelled period or a grace period, and the next billing date's changes
    (story 11.3). If the provider can't be reached, the worker tries again."""
    check_subscription(db, get_payment_provider(), uuid.UUID(payload["subscription_id"]))


@handles(family.SYNC_JOB)
def sync_family_members(db: Session, payload: dict[str, Any]) -> None:
    """Family members follow the Family plan (story 11.3): turned off when it ends, back on
    when it's active again."""
    family.sync(db, uuid.UUID(payload["account_id"]))
