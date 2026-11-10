"""Keeping the health profile up to date (story 6.1 section 7): the client is reminded to review
it 3, 6 and 12 months after the last update (`settings.health_profile_review_months`), and after
a logged provider visit. The notices go through app/notifications/service.py, which applies the
client's preferences and 12.1's "when not to send" rules again when each one is due.
"""

import calendar
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.config import settings
from app.health.models import HealthProfile
from app.notifications import service as notifications
from app.profiles.models import Profile

REVIEW = "health_profile_review"
REVIEW_AFTER_VISIT = "health_profile_review_after_visit"


def add_months(moment: datetime, months: int) -> datetime:
    """The same day `months` later, or the month's last day (31 January + 1 is 28 February)."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    return moment.replace(
        year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1])
    )


def _time_text(months: int) -> str:
    """For the notice's [time]: "It’s been 6 months since we last updated your profile." """
    return "1 month" if months == 1 else f"{months} months"


def record_update(
    db: Session, account: User, profile: Profile, now: datetime | None = None
) -> None:
    """Called after every change to the health profile, and when the intake is completed. Saves
    when it changed, and moves the review reminders: the waiting ones are cancelled and new
    ones scheduled from now. Doesn't commit."""
    now = now or datetime.now(UTC)
    db.execute(
        insert(HealthProfile)
        .values(profile_id=profile.id, updated_at=now)
        .on_conflict_do_update(index_elements=[HealthProfile.profile_id], set_={"updated_at": now})
    )
    notifications.cancel_scheduled(db, account, kind=REVIEW, profile=profile)
    for months in settings.health_profile_review_months:
        notifications.schedule(
            db,
            account,
            REVIEW,
            add_months(now, months),
            profile=profile,
            data={"time": _time_text(months)},
        )


def visit_logged(db: Session, account: User, profile: Profile) -> None:
    """For Phase 6 (story 5.2) to call when a provider visit is logged: "You’ve logged a visit.
    Has anything changed in your health profile?" Sent now. It doesn't count as an update, so
    the 3, 6 and 12 month reminders stay where they are. Doesn't commit."""
    notifications.notify(db, account, REVIEW_AFTER_VISIT, profile=profile)
