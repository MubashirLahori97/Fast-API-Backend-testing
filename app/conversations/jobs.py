"""Background jobs for conversations, run by app/worker.py."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.auth.models import User
from app.conversations.models import Conversation, Message
from app.conversations.service import SAFETY_CHECK_JOB, check_message_safety
from app.oracle.contract import OracleError
from app.oracle.dependencies import get_oracle
from app.worker import handles


@handles(SAFETY_CHECK_JOB)
def retry_safety_check(db: Session, payload: dict[str, Any]) -> None:
    """Story 3.2: every message is checked, even when no reply is asked for (before the Health
    Consent, say). Each message gets one of these jobs; it does nothing once a check has
    succeeded, and fails while the check keeps failing, so the worker tries again.

    Story 11.4: once the account's consent is withdrawn (revoked, or the account waits for
    deletion), the Oracle mustn't get its messages, so the job finishes without checking. The
    message stays unchecked: no reply or summary is given until a check succeeds, and the
    reply step checks it first if the client consents again."""
    message = db.get(Message, uuid.UUID(payload["message_id"]))
    if message is None or message.safety_level is not None:
        return  # deleted, or already checked
    profile = db.get(Conversation, message.conversation_id).profile
    if accounts.consent_withdrawn(db, db.get(User, profile.account_id)):
        return
    if check_message_safety(db, message, profile, get_oracle()) is None:
        raise OracleError("The safety check is still failing.")
