"""The reminders Phase 5 schedules, through the notifications package (story 12.1):

- 3.3: a follow-up check-in two weeks after a summary (`guidance_follow_up`, about the
  conversation);
- 3.4: with an appointment date, a reminder before it and a follow-up after it; without one, a
  booking follow-up after 7 days (about the notes).

The notifications package checks the client's preferences and 3.2's "no check-ins after an
emergency or crisis" when each one is scheduled and again when it's due. Job payloads hold ids
only. Nothing here commits: the reminders are saved with the caller's own changes.

This module doesn't import the conversations service, so deleting a conversation can call it.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.conversations.models import Conversation
from app.core.config import settings
from app.guidance.models import ProviderNote
from app.notifications import service as notifications
from app.profiles.models import Profile

GUIDANCE_FOLLOW_UP = "guidance_follow_up"
APPOINTMENT_REMINDER = "appointment_reminder"
APPOINTMENT_FOLLOW_UP = "appointment_follow_up"
BOOKING_FOLLOW_UP = "booking_follow_up"
APPOINTMENT_KINDS = (APPOINTMENT_REMINDER, APPOINTMENT_FOLLOW_UP, BOOKING_FOLLOW_UP)


def _send_time(day: date) -> datetime:
    """The day's reminder time. One hour in UTC for everyone until question 8 gives clients'
    time zones."""
    return datetime.combine(day, time(settings.appointment_reminder_hour_utc), tzinfo=UTC)


def schedule_guidance_follow_up(
    db: Session, account: User, profile: Profile, conversation: Conversation
) -> None:
    """3.3: "A follow-up check-in is sent two weeks later". An updated summary moves it to two
    weeks after the update, so there's only ever one per conversation."""
    notifications.cancel_scheduled(db, account, kind=GUIDANCE_FOLLOW_UP, target_id=conversation.id)
    notifications.schedule(
        db,
        account,
        GUIDANCE_FOLLOW_UP,
        datetime.now(UTC) + timedelta(days=settings.guidance_follow_up_days),
        profile=profile,
        target_id=conversation.id,
    )


def schedule_appointment(db: Session, account: User, profile: Profile, note: ProviderNote) -> None:
    """3.4: with a date, a reminder `appointment_reminder_days_before` it (unless that time has
    passed) and a follow-up `appointment_follow_up_days_after` it; with no date, the booking
    follow-up after `booking_follow_up_days`. Replaces whatever was scheduled for these notes,
    so it's called again whenever the date changes or is removed."""
    for kind in APPOINTMENT_KINDS:
        notifications.cancel_scheduled(db, account, kind=kind, target_id=note.id)
    now = datetime.now(UTC)
    if note.appointment_date is None:
        notifications.schedule(
            db,
            account,
            BOOKING_FOLLOW_UP,
            now + timedelta(days=settings.booking_follow_up_days),
            profile=profile,
            target_id=note.id,
        )
        return
    reminder_at = _send_time(
        note.appointment_date - timedelta(days=settings.appointment_reminder_days_before)
    )
    if reminder_at > now:
        notifications.schedule(
            db, account, APPOINTMENT_REMINDER, reminder_at, profile=profile, target_id=note.id
        )
    notifications.schedule(
        db,
        account,
        APPOINTMENT_FOLLOW_UP,
        _send_time(
            note.appointment_date + timedelta(days=settings.appointment_follow_up_days_after)
        ),
        profile=profile,
        target_id=note.id,
    )


def conversation_deleted(db: Session, conversation: Conversation, account: User) -> None:
    """Question 45: a deleted conversation's summary and notes are gone from every list and
    lookup, so the reminders about them are cancelled too."""
    notifications.cancel_scheduled(db, account, kind=GUIDANCE_FOLLOW_UP, target_id=conversation.id)
    note_ids = db.scalars(
        select(ProviderNote.id).where(ProviderNote.conversation_id == conversation.id)
    ).all()
    for note_id in note_ids:
        notifications.cancel_scheduled(db, account, target_id=note_id)
