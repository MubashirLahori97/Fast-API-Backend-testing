from datetime import date

from fastapi import APIRouter

from app.admin.dashboard import service
from app.admin.dashboard.schemas import DashboardOut, Interval
from app.admin.dependencies import AdminBackgroundSession, AdminSession
from app.core.database import DbSession

router = APIRouter(prefix="/admin/dashboard", tags=["admin: dashboard"])


@router.get("", response_model_exclude_none=True)
def dashboard(
    session: AdminSession,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    interval: Interval | None = None,
) -> DashboardOut:
    """Super Admin and Admin 2.1: Needs Attention (what's open now), the KPI cards and the
    graphs for the date range (UTC days, both included; the last 30 days by default), with
    weekly or monthly periods. Admins don't get the subscription and free trial metrics or
    Content to review: those fields are left out of the response."""
    return service.dashboard(db, session.user, date_from, date_to, interval)


@router.get("/refresh", response_model_exclude_none=True)
def refresh_dashboard(
    session: AdminBackgroundSession,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    interval: Interval | None = None,
) -> DashboardOut:
    """The same, for the admin panel's own polling (2.1: the numbers update in real time). It
    doesn't count as activity, so an unused tab is still signed out after 15 minutes."""
    return service.dashboard(db, session.user, date_from, date_to, interval)
