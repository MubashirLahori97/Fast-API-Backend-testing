import uuid
from typing import Annotated

from fastapi import Depends

from app.accounts.dependencies import ClientSession
from app.conversations.models import Conversation
from app.core.database import DbSession
from app.core.errors import AppError
from app.guidance.models import ProviderNote
from app.guidance.service import NOTES_NOT_FOUND
from app.profiles.models import Profile


def owned_provider_note(notes_id: uuid.UUID, session: ClientSession, db: DbSession) -> ProviderNote:
    """The notes in the URL, if their profile belongs to the signed-in account and their
    conversation wasn't deleted. Any other notes, including a teen's own notes seen from the
    parent's account, get the same 404, so ids can't be probed."""
    note = db.get(ProviderNote, notes_id)
    if note is not None:
        conversation = db.get(Conversation, note.conversation_id)
        profile = db.get(Profile, note.profile_id)
        if (
            conversation is not None
            and conversation.deleted_at is None
            and conversation.profile_id == note.profile_id
            and profile is not None
            and profile.account_id == session.user_id
        ):
            return note
    raise AppError(404, "provider_notes_not_found", NOTES_NOT_FOUND)


OwnedProviderNote = Annotated[ProviderNote, Depends(owned_provider_note)]
