import uuid
from typing import Annotated

from fastapi import Depends

from app.accounts.dependencies import ClientSession
from app.conversations.models import Conversation
from app.conversations.service import CONVERSATION_NOT_FOUND
from app.core.database import DbSession
from app.core.errors import AppError
from app.profiles.models import Profile


def owned_conversation(
    conversation_id: uuid.UUID, session: ClientSession, db: DbSession
) -> Conversation:
    """The conversation in the URL, if its profile belongs to the signed-in account. Any
    other conversation, including one that doesn't exist or was deleted, gets the same 404."""
    conversation = db.get(Conversation, conversation_id)
    if (
        conversation is None
        or conversation.deleted_at is not None
        or db.get(Profile, conversation.profile_id).account_id != session.user_id
    ):
        raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
    return conversation


OwnedConversation = Annotated[Conversation, Depends(owned_conversation)]
