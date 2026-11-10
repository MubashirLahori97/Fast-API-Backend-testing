"""The records notifications open, and the health details shown from them.

A kind with `target` set links to one record through `notifications.target_id`. Each target
type has a lookup here that says whether the record still exists, and gives the [topic] or
[specialty] it shows. Those details are health data, so they're read from the record when the
list is shown and never stored with the notification.

Later phases add their target types to LOOKUPS, as "provider_note" (Phase 5, 3.4: the specialty)
and "visit_log" (Phase 6, 5.2) are. A type with no lookup always opens and shows the kind's
generic text.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.conversations.models import Conversation


@dataclass(frozen=True)
class Target:
    exists: bool
    details: dict[str, str] = field(default_factory=dict)  # keys of DETAIL_PLACEHOLDERS


# (db, target_id, profile_id) -> Target. The profile id lets a lookup refuse a record that
# isn't the notification's profile's.
Lookup = Callable[[Session, uuid.UUID, uuid.UUID | None], Target]


def _conversation(db: Session, target_id: uuid.UUID, profile_id: uuid.UUID | None) -> Target:
    conversation = db.get(Conversation, target_id)
    if (
        conversation is None
        or conversation.deleted_at is not None
        or conversation.profile_id != profile_id
    ):
        return Target(exists=False)
    return Target(exists=True, details={"topic": conversation.topic} if conversation.topic else {})


def _provider_note(db: Session, target_id: uuid.UUID, profile_id: uuid.UUID | None) -> Target:
    """Phase 5 (3.4): the notes' [specialty]; gone with their conversation."""
    from app.guidance.models import ProviderNote
    from app.guidance.specialties import label

    note = db.get(ProviderNote, target_id)
    conversation = note and db.get(Conversation, note.conversation_id)
    if (
        note is None
        or note.profile_id != profile_id
        or conversation is None
        or conversation.deleted_at is not None
    ):
        return Target(exists=False)
    return Target(exists=True, details={"specialty": label(note.specialty, note.specialty_other)})


def _visit_log(db: Session, target_id: uuid.UUID, profile_id: uuid.UUID | None) -> Target:
    """Phase 6 (5.2): a deleted visit log's reminders aren't sent."""
    from app.visits.models import VisitLog

    log = db.get(VisitLog, target_id)
    if log is None or log.profile_id != profile_id:
        return Target(exists=False)
    return Target(exists=True)


LOOKUPS: dict[str, Lookup] = {
    "conversation": _conversation,
    "provider_note": _provider_note,
    "visit_log": _visit_log,
}


def look_up(
    db: Session, target: str | None, target_id: uuid.UUID | None, profile_id: uuid.UUID | None
) -> Target:
    """The linked record, or an always-open one for notices that link to no record or to a
    type with no lookup yet."""
    if target is None or target_id is None:
        return Target(exists=True)
    lookup = LOOKUPS.get(target)
    if lookup is None:
        return Target(exists=True)
    return lookup(db, target_id, profile_id)
