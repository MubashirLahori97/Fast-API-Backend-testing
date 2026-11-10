from typing import Annotated

from fastapi import APIRouter, Query

from app.accounts.dependencies import ClientSession
from app.core.database import DbSession
from app.dashboard import service
from app.dashboard.schemas import HomeDashboardOut
from app.profiles.dependencies import UsableProfile

router = APIRouter(prefix="/profiles", tags=["home dashboard"])

# An IANA time zone name such as "America/Chicago": letters, digits and _ + - / only.
TimeZone = Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9_+/-]+$")]


@router.get("/{profile_id}/dashboard")
def get_dashboard(
    profile: UsableProfile,
    session: ClientSession,
    db: DbSession,
    time_zone: TimeZone = None,
) -> HomeDashboardOut:
    """Story 4.1's Home Dashboard for the active profile: the top bar, the trial banner or the
    upgrade prompt, and every widget in the story's order with `shown` and `locked`.

    - Send the device's `time_zone` for the greeting's time of day.
    - Another account's profile, a teen's own included, gets the same 404 as an unknown one.
    - A turned-off member, one being deleted or an unfinished intake gets 409: the app switches
      to the default profile (`GET /me/next-step`).
    - 503 `load_failed`: "We couldn’t load your dashboard. Please try again."

    Read-only: it's not a message, marks nothing read and starts nothing."""
    return service.dashboard(db, profile, session.user, time_zone)
