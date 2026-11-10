"""Helpers the admin panel's operations share (Phase A part 2: dashboard, clients, escalations,
support, deletions, knowledge, plans and policies)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import Query
from sqlalchemy import ColumnElement, and_, func, or_

from app.auth.models import User
from app.billing.models import Subscription
from app.core.config import settings

# Super Admin 5.1's confirmation, used for every notes field.
NOTE_SAVED = "Your note has been saved."

Limit = Annotated[int, Query(ge=1, le=settings.admin_list_max_limit)]
Offset = Annotated[int, Query(ge=0)]


def like(text: str) -> str:
    """An ILIKE pattern that matches `text` anywhere, with its own % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def day_start(day: date) -> datetime:
    """Midnight UTC at the start of `day`. The admin panel's date filters are UTC days."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def day_range(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """A filter's from and to dates as [from, to): both days are included."""
    return (
        day_start(start) if start is not None else None,
        day_start(end + timedelta(days=1)) if end is not None else None,
    )


def format_date(value: date | datetime) -> str:
    """ "December 5, 2026", as in the billing messages."""
    day = value.date() if isinstance(value, datetime) else value
    return f"{day:%B} {day.day}, {day.year}"


def is_teen() -> ColumnElement[bool]:
    """SQL for support.service.is_teen_account: a teen with their own account (story 1.5). It
    stays a teen account after the age of majority until the teen creates their adult one
    (1.6)."""
    return User.account_type == "teen"


def subscription_gives_access(now: datetime) -> ColumnElement[bool]:
    """SQL for billing.entitlements.gives_access, on an outer-joined Subscription."""
    return or_(
        Subscription.status == "active",
        and_(Subscription.status == "past_due", Subscription.grace_ends_at > now),
        and_(
            Subscription.status == "cancelled",
            func.greatest(
                Subscription.current_period_end,
                func.coalesce(Subscription.grace_ends_at, Subscription.current_period_end),
            )
            > now,
        ),
    )


def business_days_left(now: datetime, due: datetime) -> int:
    """Weekdays from today to the due date (Super Admin 5.2's "days remaining"); negative once
    it's overdue. Public holidays aren't counted yet, like privacy.service.add_business_days."""
    start, end = now.date(), due.date()
    step = 1 if end >= start else -1
    count = 0
    day = start
    while day != end:
        day += timedelta(days=step)
        if day.weekday() < 5:
            count += step
    return count
