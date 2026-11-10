"""The admin notification centre and its preferences (Super Admin 11.1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.admin.notifications.kinds import Category, Screen
from app.core.schemas import RequestBody


class AdminNotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    category: Category
    title: str
    body: str
    screen: Screen
    target_id: uuid.UUID | None
    read: bool
    created_at: datetime


class AdminNotificationPage(BaseModel):
    items: list[AdminNotificationOut]
    unread_count: int
    # Pass as ?before= for the next, older page; null on the last page.
    next_before: uuid.UUID | None
    # "You’re all caught up." when there are no notifications at all.
    message: str | None = None


class UnreadCount(BaseModel):
    unread_count: int


class AdminPreferenceOut(BaseModel):
    category: Category
    label: str
    email: bool
    # False for deletion deadline reminders: shown, but always emailed.
    can_turn_off: bool


class AdminPreferencesOut(BaseModel):
    preferences: list[AdminPreferenceOut]


class AdminPreferencesUpdated(AdminPreferencesOut):
    message: str


class AdminPreferenceIn(RequestBody):
    category: Category
    email: bool


class AdminPreferencesIn(RequestBody):
    """The types to change; types left out keep their current choice, so the panel can send
    one row or the whole screen. In-app notifications are always on."""

    preferences: list[AdminPreferenceIn]
