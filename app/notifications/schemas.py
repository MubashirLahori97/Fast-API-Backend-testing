"""Notification centre, preferences and push tokens (story 12.1)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from app.core.schemas import RequestBody
from app.notifications.kinds import Category, Screen


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    category: Category
    title: str
    body: str
    # The profile it's about, shown with the message (12.1: for example "Azka"), and the one to
    # switch to when it's opened. Null for notices about the account.
    profile_id: uuid.UUID | None
    profile_name: str | None
    screen: Screen
    target_id: uuid.UUID | None
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread_count: int
    # Pass as ?before= to get the next, older page; null on the last page.
    next_before: uuid.UUID | None
    # "You’re all caught up." when the client has no notifications at all.
    message: str | None = None


class UnreadCount(BaseModel):
    unread_count: int


class PreferenceOut(BaseModel):
    category: Category
    label: str
    enabled: bool
    push: bool
    email: bool
    # False for billing, requests and account, and teen safety and access: shown, but fixed.
    can_turn_off: bool


class PreferencesOut(BaseModel):
    preferences: list[PreferenceOut]


class PreferencesUpdated(PreferencesOut):
    message: str


class PreferenceIn(RequestBody):
    """One type's choice. With enabled true and neither push nor email, notices of this type
    still appear in the notification centre."""

    category: Category
    enabled: bool
    push: bool
    email: bool


class PreferencesIn(RequestBody):
    """The types to change. Types left out keep their current choice, so the app can send one
    row or the whole screen."""

    preferences: list[PreferenceIn]


class PushTokenIn(RequestBody):
    """The token the phone's push service gave the app. Send it after every sign-in, and again
    when the service gives the app a new one."""

    token: str
    platform: Literal["ios", "android"]

    @field_validator("token")
    @classmethod
    def check_token(cls, value: str) -> str:
        value = value.strip()
        # Provider tokens are printable ASCII without spaces (FCM, APNs, Expo).
        if not value or not value.isascii() or not value.isprintable() or " " in value:
            raise ValueError("This push token isn’t valid.")
        return value


class PushTokenOut(BaseModel):
    id: uuid.UUID
    platform: Literal["ios", "android"]
    created_at: datetime
