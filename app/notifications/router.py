import uuid

from fastapi import APIRouter, Query, Response

from app.accounts.dependencies import ClientBackgroundSession, ClientSession
from app.auth.dependencies import CurrentSession
from app.core.config import settings
from app.core.database import DbSession
from app.notifications import service
from app.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    PreferencesIn,
    PreferencesOut,
    PreferencesUpdated,
    PushTokenIn,
    PushTokenOut,
    UnreadCount,
)

router = APIRouter(tags=["notifications"])


@router.get("/me/notifications")
def list_notifications(
    session: ClientSession,
    db: DbSession,
    before: uuid.UUID | None = None,
    limit: int = Query(
        default=settings.notifications_page_size, ge=1, le=settings.notifications_max_page_size
    ),
) -> NotificationPage:
    """Story 12.1's notification centre, newest first. For the next page, pass the
    `next_before` of this one as `before`."""
    return service.list_notifications(db, session.user, before, limit)


@router.get("/me/notifications/unread-count")
def unread_count(session: ClientBackgroundSession, db: DbSession) -> UnreadCount:
    """The number on the bell (stories 4.1 and 12.1). Apps poll it, so it doesn't count as
    activity for the web's 30-minute idle timeout."""
    return UnreadCount(unread_count=service.unread_count(db, session.user))


@router.post("/me/notifications/read-all")
def mark_all_read(session: ClientSession, db: DbSession) -> UnreadCount:
    """Story 12.1's mark all as read: the count clears."""
    service.mark_all_read(db, session.user)
    return UnreadCount(unread_count=0)


@router.post("/me/notifications/{notification_id}/read")
def open_notification(
    notification_id: uuid.UUID, session: ClientSession, db: DbSession
) -> NotificationOut:
    """The client tapped a notification: marks it read and returns where it goes (screen,
    profile, record). 410 with "This item is no longer available." when that's gone."""
    return service.open_notification(db, session.user, notification_id)


@router.get("/me/notification-preferences")
def get_preferences(session: ClientSession, db: DbSession) -> PreferencesOut:
    """Story 12.1's Notification Preferences, including the types that can't be turned off."""
    return PreferencesOut(preferences=service.get_preferences(db, session.user))


@router.put("/me/notification-preferences")
def update_preferences(
    data: PreferencesIn, session: ClientSession, db: DbSession
) -> PreferencesUpdated:
    preferences = service.update_preferences(db, session.user, data.preferences)
    return PreferencesUpdated(message=service.PREFERENCES_UPDATED, preferences=preferences)


# Push devices take a plain signed-in session, not the policy gate: the app registers its token
# straight after sign-in and removes it at sign-out, and neither shows any health information.


@router.post("/me/push-tokens", status_code=201)
def register_push_token(data: PushTokenIn, session: CurrentSession, db: DbSession) -> PushTokenOut:
    """Registers this device for push notifications (story 12.1). Send it after every sign-in:
    signing out, or any change that ends every session, stops the device's pushes."""
    token = service.register_push_token(db, session, data)
    return PushTokenOut(id=token.id, platform=token.platform, created_at=token.created_at)


@router.delete("/me/push-tokens/{token_id}", status_code=204)
def remove_push_token(token_id: uuid.UUID, session: CurrentSession, db: DbSession) -> Response:
    """This device stops getting pushes, e.g. when the client turns them off in the app."""
    service.remove_push_token(db, session.user, token_id)
    return Response(status_code=204)
