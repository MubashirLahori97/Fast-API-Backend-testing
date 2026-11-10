import uuid

from fastapi import APIRouter, Query

from app.admin.dependencies import AdminBackgroundSession, AdminSession
from app.admin.notifications import service
from app.admin.notifications.schemas import (
    AdminNotificationOut,
    AdminNotificationPage,
    AdminPreferencesIn,
    AdminPreferencesOut,
    AdminPreferencesUpdated,
    UnreadCount,
)
from app.core.config import settings
from app.core.database import DbSession

router = APIRouter(prefix="/admin", tags=["admin: notifications"])


@router.get("/notifications")
def list_notifications(
    session: AdminSession,
    db: DbSession,
    before: uuid.UUID | None = None,
    limit: int = Query(
        default=settings.notifications_page_size, ge=1, le=settings.notifications_max_page_size
    ),
) -> AdminNotificationPage:
    """Super Admin 11.1's notification centre, newest first, with the bell's unread count. For
    the next page, pass this page's `next_before` as `before`."""
    return service.list_notifications(db, session.user, before, limit)


@router.get("/notifications/unread-count")
def unread_count(session: AdminBackgroundSession, db: DbSession) -> UnreadCount:
    """The number on the bell. The panel polls it, so it doesn't count as activity for the
    15-minute inactivity sign-out."""
    return UnreadCount(unread_count=service.unread_count(db, session.user))


@router.post("/notifications/read-all")
def mark_all_read(session: AdminSession, db: DbSession) -> UnreadCount:
    service.mark_all_read(db, session.user)
    return UnreadCount(unread_count=0)


@router.post("/notifications/{notification_id}/read")
def open_notification(
    notification_id: uuid.UUID, session: AdminSession, db: DbSession
) -> AdminNotificationOut:
    """The admin selected a notification: marks it read and returns the screen and record to
    open."""
    return service.open_notification(db, session.user, notification_id)


@router.get("/notification-preferences")
def get_preferences(session: AdminSession, db: DbSession) -> AdminPreferencesOut:
    """Email on or off per type (11.1). In-app notifications are always on; deletion deadline
    reminders are always emailed."""
    return AdminPreferencesOut(preferences=service.get_preferences(db, session.user))


@router.put("/notification-preferences")
def update_preferences(
    data: AdminPreferencesIn, session: AdminSession, db: DbSession
) -> AdminPreferencesUpdated:
    preferences = service.update_preferences(db, session.user, data.preferences)
    return AdminPreferencesUpdated(message=service.PREFERENCES_UPDATED, preferences=preferences)
