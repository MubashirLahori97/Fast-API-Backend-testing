"""Conversations with the Oracle (story 3.1), and the safety path (story 3.2).

A message is sent in two steps, so a lost connection never loses anything:

1. `start_conversation` or `send_message` saves the client message, then runs the safety check
   (story 3.2) outside any transaction or lock. It answers with what the app does next: show
   the emergency or crisis screen, ask for the reply, or show the Health Consent first.
2. `prepare_reply` checks the gates and claims the message, then `reply_events` streams the
   Oracle's reply as server-sent events and saves it once it's complete. After a lost
   connection the app asks again: a saved reply is sent whole, and an unsaved one is generated
   again, up to `reply_max_attempts` times.

An emergency or a crisis puts the conversation on hold (app/conversations/safety.py): no reply
is given until the client picks an option with `choose_safety_option`.

The packages built since (docs/decisions/integration-conversations.md):

- the Oracle gets the health profile with every reply (`health_context`, story 6.1), so it
  never asks again for what's known (3.1);
- health_fact widgets are saved straight to the health profile with the reply
  (`_save_health_details`), marked as added from the conversation (3.1, 3.3 and 6.1 of the
  6 Nov 19:22 stories: nothing is confirmed first, and no card is shown in the chat);
- `request_support` sends a knowledge gap or a request for a person to the support team when
  the client accepts the Oracle's offer (story 10.1).

Message text, topics, widgets, answers and the profile context are health data: never logged,
audited or put in error messages. Oracle failures are logged by class name only.
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import get_args

from fastapi import Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts.models import PolicyVersion
from app.auth.models import User
from app.billing import entitlements
from app.conversations import safety
from app.conversations.models import Conversation, HealthConsent, Message, MessageFeedback
from app.conversations.schemas import (
    ChooseSafetyOption,
    ConversationOut,
    ConversationSummary,
    FeedbackOut,
    GiveFeedback,
    MessageOut,
    MessageSent,
    NewConversation,
    RequestSupport,
    SendMessage,
    SupportRequestFromConversation,
)
from app.conversations.starters import starter_questions
from app.conversations.widgets import (
    closing_widgets,
    prepare_widget,
    support_request_sent,
)
from app.core import audit, jobs
from app.core.ages import age_group, is_adult
from app.core.config import settings
from app.core.errors import ACTION_FAILED, AppError, database_errors_retryable
from app.core.schemas import clean_line
from app.health import service as health_service
from app.oracle.contract import (
    HEALTH_FACT,
    SUPPORT_OFFER,
    SUPPORT_REQUEST_SENT,
    EarlierConversation,
    HealthAnswer,
    HealthContext,
    HealthQuestion,
    Oracle,
    OracleError,
    ProfileContext,
    SafetyContext,
    SafetyLevel,
    Turn,
    Widget,
)
from app.profiles.models import Profile
from app.profiles.service import check_can_use
from app.support import service as support_service

logger = logging.getLogger(__name__)

HEALTH_CONSENT_REQUIRED = "Please accept the Health Consent so I can help you."
CONVERSATION_NOT_FOUND = "We couldn’t find that conversation."
# Not in the stories; worded like 5.2's "We couldn’t delete your visit log just now..."
DELETE_FAILED = "We couldn’t delete this conversation just now. Please try again."
TOO_MANY_MESSAGES = (
    "You’re sending messages faster than I can keep up with. Please wait a few minutes and try "
    "again."
)
TOO_MANY_CONVERSATIONS = (
    "You’ve started a lot of conversations today. Please carry on in one of them, or try again "
    "tomorrow."
)
REPLY_IN_PROGRESS = "I’m still replying to that message. Please wait a moment."
TOO_MANY_ATTEMPTS = "I couldn’t reply to that message. Please try sending it again."
SAFETY_LEVELS = frozenset(get_args(SafetyLevel))
SAFETY_CHECK_JOB = "conversations.safety_check"  # see app/conversations/jobs.py
TOPIC_MAX_LENGTH = 100

# Each reply stream holds a worker thread for as long as the Oracle takes, so they're capped,
# leaving threads for every other request (docs/PLAN.md: an async Oracle client removes this).
_reply_streams = threading.BoundedSemaphore(settings.max_reply_streams)


def _safety_hold_error() -> AppError:
    """Story 3.2's "Option not selected": the conversation is paused until an option is picked."""
    return AppError(409, "safety_hold", safety.OPTION_NOT_SELECTED)


def profile_context(profile: Profile, account: User, db: Session | None = None) -> ProfileContext:
    """Story 3.1 section 5. Fields are picked one by one, never the whole row. Names and
    write-ins are cleaned again here, for rows saved before the rules were tightened.

    With `db`, it also carries the health profile (`health_context`), the logged visits (5.2)
    and the Wellness Plan (7.1), which read the database: commit before the Oracle call, so no
    transaction is held while it runs. Without it, they're left empty."""
    # Imported here: both packages use this module.
    from app.visits.service import oracle_visits
    from app.wellness.service import oracle_plan

    first_name = account.first_name if profile.is_self else profile.first_name
    return ProfileContext(
        is_self=profile.is_self,
        first_name=clean_line(first_name),
        advocate_first_name=clean_line(account.first_name),
        relationship=profile.family_relationship,
        age_group=age_group(profile.date_of_birth),
        sex_at_birth=profile.sex_at_birth,
        gender_identity=profile.gender_identity,
        gender_identity_other=_clean_or_none(profile.gender_identity_other),
        pronouns=profile.pronouns,
        pronouns_other=_clean_or_none(profile.pronouns_other),
        health=health_context(db, profile, account) if db is not None else HealthContext(),
        visits=oracle_visits(db, profile) if db is not None else (),
        wellness_plan=oracle_plan(db, profile) if db is not None else None,
        # Story 3.1's "teen with their own account" (Phase 3b): education only, in private.
        teen_own_account=support_service.is_teen_account(account),
    )


def _clean_or_none(value: str | None) -> str | None:
    return clean_line(value) or None if value else None


def health_context(db: Session, profile: Profile, account: User) -> HealthContext:
    """Story 6.1's health profile for the Oracle: the answered questions that apply (story 3.1's
    "Never repeat") and the ones still open, with the codes a health_fact widget uses. Copied
    field by field into the contract's types. Health data: never logged."""
    answered = tuple(
        HealthAnswer(
            key=known.key,
            section=known.section,
            question=known.question,
            answer=known.answer,
            value=known.value,
            other=known.other,
            sensitive=known.sensitive,
            from_conversation=known.from_conversation,
            updated_at=known.updated_at,
        )
        for known in health_service.health_context(db, profile, account)
    )
    unanswered = tuple(
        HealthQuestion(
            key=question.key,
            section=question.section,
            question=question.question,
            kind=question.kind,
            choices=question.choices,
            write_in_choice=question.write_in_choice,
            optional=question.optional,
            sensitive=question.sensitive,
        )
        for question in health_service.open_questions(db, profile, account)
    )
    return HealthContext(answered=answered, unanswered=unanswered)


def _turn(message: Message) -> Turn:
    return Turn(
        role=message.role,
        text=message.text,
        widgets=message.widgets or [],
        answer=message.answer,
    )


# The Health Consent (story 3.1)


def current_health_consent(db: Session) -> PolicyVersion:
    policy = db.scalars(
        select(PolicyVersion)
        .where(
            PolicyVersion.kind == "health_consent",
            PolicyVersion.published_at <= datetime.now(UTC),
        )
        .order_by(PolicyVersion.published_at.desc())
        .limit(1)
    ).first()
    if policy is None:
        # Seeded by a migration, so this is a broken deployment. Never skip the consent.
        raise AppError(503, "health_consent_unavailable", ACTION_FAILED)
    return policy


def has_health_consent(db: Session, profile: Profile) -> bool:
    """The current version is accepted for this profile, by the account that holds it now.
    Asked once per profile, and again when The Oracle's team publishes a new version.

    A teen with their own account never sees it: the parent's consent for them counts (3.1),
    given at the invite and confirmed again for each new version (12.2, app/teens/access.py)."""
    policy = current_health_consent(db)
    account = db.get(User, profile.account_id)
    if account is not None and support_service.is_teen_account(account):
        from app.teens import access as teen_access  # Phase 3b; app.teens uses app.billing

        return teen_access.parent_consent_covers(db, account, policy.id)
    accepted = db.scalar(
        select(HealthConsent.id).where(
            HealthConsent.profile_id == profile.id,
            HealthConsent.policy_version_id == policy.id,
            HealthConsent.accepted_by_id == profile.account_id,
        )
    )
    return accepted is not None


def accept_health_consent(
    db: Session,
    profile: Profile,
    policy_version_id: uuid.UUID | None,
    account: User,
    request: Request,
) -> None:
    """The client accepts for themself, or confirms they're the family member's medical
    advocate and accepts for them. Only the current version counts."""
    policy = current_health_consent(db)
    if policy_version_id is None:
        raise AppError(422, "health_consent_required", HEALTH_CONSENT_REQUIRED, "policy_version_id")
    if policy_version_id != policy.id:
        # A newer version was published since the app showed it: the app fetches the current
        # one and shows that.
        raise AppError(409, "health_consent_outdated", HEALTH_CONSENT_REQUIRED, "policy_version_id")
    if has_health_consent(db, profile):
        return
    with database_errors_retryable(db):
        db.add(
            HealthConsent(
                profile_id=profile.id, policy_version_id=policy.id, accepted_by_id=account.id
            )
        )
        audit.record(
            db,
            "health_consent.accepted",
            actor_id=account.id,
            target_type="profile",
            target_id=profile.id,
            request=request,
            details={"version": policy.version},
        )
        try:
            db.commit()
        except IntegrityError:  # accepted twice at once; the other request saved it
            db.rollback()


# Starting and listing conversations


def _opening(profile: Profile) -> str:
    if profile.is_self:
        return "How are you feeling today?"
    return f"How is {profile.first_name} feeling today?"


def new_conversation(profile: Profile, account: User) -> NewConversation:
    first_name = account.first_name if profile.is_self else profile.first_name
    return NewConversation(
        opening=_opening(profile), starters=starter_questions(profile.is_self, first_name)
    )


def list_conversations(
    db: Session, profile: Profile, limit: int | None = None
) -> list[ConversationSummary]:
    """The profile's conversations, most recent first (story 3.1, Returning Client), each
    marked when it's paused by an emergency or crisis hold (story 3.2). `limit` keeps only the
    newest ones (the Home Dashboard needs just one)."""
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.profile_id == profile.id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
    )
    held = safety.held_conversations(db, [conversation.id for conversation in conversations])
    return [
        ConversationSummary.model_validate(conversation).model_copy(
            update={"safety_hold": conversation.id in held}
        )
        for conversation in conversations
    ]


def _messages(db: Session, conversation: Conversation) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    )


def _unchecked_messages(db: Session, conversation: Conversation) -> list[Message]:
    """Client messages whose safety check hasn't succeeded yet."""
    return list(
        db.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role == "client",
                Message.safety_level.is_(None),
            )
        )
    )


def _last_client_message(messages: list[Message]) -> Message | None:
    return next((message for message in reversed(messages) if message.role == "client"), None)


def _reply_to(messages: list[Message], message: Message) -> Message | None:
    return next((reply for reply in messages if reply.reply_to_id == message.id), None)


def _welcome_back(conversation: Conversation, account: User) -> str | None:
    """Story 3.1's line for a conversation picked up after a while."""
    returning_after = timedelta(hours=settings.welcome_back_after_hours)
    if not conversation.topic or conversation.last_message_at > datetime.now(UTC) - returning_after:
        return None
    return (
        f"Welcome back, {account.first_name}. Last time we talked about {conversation.topic}. "
        "How have things been since then?"
    )


def conversation_out(db: Session, conversation: Conversation, account: User) -> ConversationOut:
    messages = _messages(db, conversation)
    last = _last_client_message(messages)
    ratings = dict(
        db.execute(
            select(MessageFeedback.message_id, MessageFeedback.rating).where(
                MessageFeedback.message_id.in_([message.id for message in messages])
            )
        ).all()
    )
    advice = safety.advice_levels(db, conversation.id)
    hold = safety.open_hold(db, conversation.id)
    return ConversationOut(
        id=conversation.id,
        profile_id=conversation.profile_id,
        topic=conversation.topic,
        created_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
        messages=[
            MessageOut.model_validate(message).model_copy(
                update={"feedback": ratings.get(message.id), "safety": advice.get(message.id)}
            )
            for message in messages
        ],
        # No reply is coming while the conversation is paused (story 3.2).
        awaiting_reply=hold is None and last is not None and _reply_to(messages, last) is None,
        welcome_back=None if hold is not None else _welcome_back(conversation, account),
        safety_hold=safety.hold_out(db, hold) if hold is not None else None,
    )


# Sending a message


def _existing_message(db: Session, profile: Profile, client_msg_id: uuid.UUID) -> Message | None:
    """A message this profile already saved with this id: a resend after a lost connection."""
    return db.scalars(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.profile_id == profile.id,
            Conversation.deleted_at.is_(None),
            Message.client_msg_id == client_msg_id,
        )
    ).first()


def _message_sent(db: Session, profile: Profile, message: Message) -> MessageSent:
    """What the app does next. An emergency or crisis hold comes first, before the Health
    Consent (story 3.2)."""
    hold = safety.open_hold(db, message.conversation_id)
    if hold is not None:
        next_step = "safety_hold"
    elif _attempts_used_up(db, message):
        next_step = "send_again"
    elif has_health_consent(db, profile):
        next_step = "reply"
    else:
        next_step = "health_consent"
    return MessageSent(
        conversation_id=message.conversation_id,
        message=MessageOut.model_validate(message),
        next=next_step,
        safety=safety.advice_for(db, message),
        safety_hold=safety.hold_out(db, hold) if hold is not None else None,
    )


def _attempts_used_up(db: Session, message: Message) -> bool:
    """Every reply attempt for this message failed, so it can only be sent again, as a new
    message with a new client_msg_id."""
    if message.reply_attempts < settings.reply_max_attempts:
        return False
    answered = db.scalar(select(Message.id).where(Message.reply_to_id == message.id))
    return answered is None


def _check_message_rate(db: Session, account: User) -> None:
    """Every message costs a safety check and a reply, so each account has an hourly limit."""
    sent = db.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Profile, Conversation.profile_id == Profile.id)
        .where(
            Profile.account_id == account.id,
            Message.role == "client",
            Message.created_at > datetime.now(UTC) - timedelta(hours=1),
        )
    )
    if sent >= settings.max_messages_per_hour:
        raise AppError(429, "too_many_messages", TOO_MANY_MESSAGES)


def _check_conversation_rate(db: Session, account: User) -> None:
    started = db.scalar(
        select(func.count())
        .select_from(Conversation)
        .join(Profile, Conversation.profile_id == Profile.id)
        .where(
            Profile.account_id == account.id,
            Conversation.created_at > datetime.now(UTC) - timedelta(days=1),
        )
    )
    if started >= settings.max_conversations_per_day:
        raise AppError(429, "too_many_conversations", TOO_MANY_CONVERSATIONS)


def _add_client_message(db: Session, conversation: Conversation, body: SendMessage) -> Message:
    """Adds the message, and a job that retries its safety check later if the first try
    fails. Both are saved by the caller's commit, so a message can't be saved without it."""
    message = Message(
        conversation_id=conversation.id,
        role="client",
        text=body.text,
        client_msg_id=body.client_msg_id,
        answer=body.answer,
        outside_us=body.outside_us,
    )
    db.add(message)
    db.flush()
    jobs.enqueue(
        db,
        SAFETY_CHECK_JOB,
        {"message_id": str(message.id)},
        run_at=datetime.now(UTC) + timedelta(seconds=settings.safety_check_retry_seconds),
    )
    conversation.last_message_at = datetime.now(UTC)
    return message


def check_message_safety(
    db: Session, message: Message, profile: Profile, oracle: Oracle
) -> str | None:
    """Story 3.2: every client message is checked, before the Health Consent and before any
    reply. Runs with no transaction or lock held. Returns the stored level, or None while no
    check has succeeded; no reply is given until one does.

    Only the first successful result is stored, so two checks of one message running at once
    (a resend and a reply, say) can't overwrite each other. The check that stores an urgent,
    emergency or crisis level also adds the advice and the escalation, in the same transaction
    (safety.record_escalation), so each message gets them exactly once."""
    context = SafetyContext(is_self=profile.is_self, age_group=age_group(profile.date_of_birth))
    try:
        result = oracle.check_safety(context, message.text)
        if result.level not in SAFETY_LEVELS:
            raise OracleError("The safety check returned an unknown level.")
    except Exception as error:  # any failure of the AI service; logged without the message
        logger.warning("Safety check failed: %s (message %s)", type(error).__name__, message.id)
        db.refresh(message)  # another check may have succeeded meanwhile
        return message.safety_level
    escalated = result.level != "none"
    with database_errors_retryable(db):
        stored = db.execute(
            update(Message)
            .where(Message.id == message.id, Message.safety_level.is_(None))
            .values(
                safety_level=result.level,
                safety_reason=safety.safety_reason(result) if escalated else None,
            )
        ).rowcount
        if stored and escalated:
            safety.record_escalation(db, message, profile, result)
        db.commit()
        db.refresh(message)
    return message.safety_level


def start_conversation(
    db: Session,
    profile: Profile,
    body: SendMessage,
    account: User,
    oracle: Oracle,
    request: Request,
) -> tuple[MessageSent, bool]:
    """A new conversation starts with the client's first message, after the Oracle's opening
    question, so there are no empty conversations. Returns (result, created). Safe to repeat
    with the same client_msg_id."""
    with database_errors_retryable(db):
        # One send at a time per profile, so a resend can't be saved twice.
        db.refresh(profile, with_for_update=True)
        check_can_use(profile)
        existing = _existing_message(db, profile, body.client_msg_id)
        if existing is not None:
            return _message_sent(db, profile, existing), False
        entitlements.check_can_talk(account)
        _check_message_rate(db, account)
        _check_conversation_rate(db, account)

        conversation = Conversation(profile_id=profile.id, last_message_at=datetime.now(UTC))
        db.add(conversation)
        db.flush()
        db.add(Message(conversation_id=conversation.id, role="oracle", text=_opening(profile)))
        db.flush()  # the opening question is saved first, so it sorts first
        message = _add_client_message(db, conversation, body)
        audit.record(
            db,
            "conversation.started",
            actor_id=account.id,
            target_type="conversation",
            target_id=conversation.id,
            request=request,
            details={"profile_id": str(profile.id)},
        )
        db.commit()
    check_message_safety(db, message, profile, oracle)
    with database_errors_retryable(db):  # saved already: a resend gets the answer
        return _message_sent(db, profile, message), True


def send_message(
    db: Session,
    conversation: Conversation,
    body: SendMessage,
    account: User,
    oracle: Oracle,
) -> tuple[MessageSent, bool]:
    """Adds a client message to an existing conversation. Returns (result, created). Safe to
    repeat with the same client_msg_id.

    During an emergency or crisis hold the message is still saved and checked (so nothing typed
    then is lost, and a new emergency in it is recorded), but it gets no reply: the answer
    says "safety_hold" until an option is picked."""
    profile = conversation.profile
    with database_errors_retryable(db):
        db.refresh(profile, with_for_update=True)  # the same lock as starting a conversation
        check_can_use(profile)
        existing = _existing_message(db, profile, body.client_msg_id)
        if existing is not None:
            return _message_sent(db, profile, existing), False
        entitlements.check_can_talk(account)
        _check_message_rate(db, account)

        # Locked, so a delete on another device either happens first (and the message is
        # refused) or waits until it's saved.
        db.refresh(conversation, with_for_update=True)
        if conversation.deleted_at is not None:
            raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
        on_hold = safety.open_hold(db, conversation.id) is not None
        welcome_back = None if on_hold else _welcome_back(conversation, account)
        if welcome_back is not None:
            # The line the app showed when the client came back, saved so the Oracle knows
            # what the client is answering.
            db.add(Message(conversation_id=conversation.id, role="oracle", text=welcome_back))
            db.flush()
        message = _add_client_message(db, conversation, body)
        db.commit()
    check_message_safety(db, message, profile, oracle)
    with database_errors_retryable(db):  # saved already: a resend gets the answer
        return _message_sent(db, profile, message), True


def choose_safety_option(
    db: Session,
    conversation: Conversation,
    body: ChooseSafetyOption,
    account: User,
    oracle: Oracle,
    request: Request,
) -> tuple[MessageSent, bool]:
    """Story 3.2: the client picks an option on the emergency or crisis screen. It closes
    every open hold in the conversation, records the choice on their escalations, and is saved
    as the client's next message (its label, with {"safety_option": ...} as the answer), so the
    Oracle's next reply knows what they chose. The answer's `next` is then the Health Consent
    or the reply, as for any message. Returns (result, created); safe to repeat with the same
    client_msg_id.

    Not refused by the trial, the rate limits, or a turned-off or deletion-requested profile:
    nothing may keep a client from answering the safety screen."""
    profile = conversation.profile
    with database_errors_retryable(db):
        db.refresh(profile, with_for_update=True)  # the same lock order as sending a message
        existing = _existing_message(db, profile, body.client_msg_id)
        if existing is not None:
            return _message_sent(db, profile, existing), False
        db.refresh(conversation, with_for_update=True)
        if conversation.deleted_at is not None:
            raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
        holds = safety.open_holds(db, conversation.id, lock=True)
        if not holds:  # answered already, on another device say
            raise AppError(409, "no_safety_hold", safety.NO_SAFETY_HOLD)
        option = safety.check_option(holds[0], body.option)
        safety.close_holds(holds, option)
        choice = SendMessage(
            client_msg_id=body.client_msg_id,
            text=safety.OPTION_LABELS[option],
            answer={"safety_option": option},
            outside_us=holds[0].outside_us,
        )
        message = _add_client_message(db, conversation, choice)
        audit.record(
            db,
            "escalation.option_chosen",
            actor_id=account.id,
            target_type="escalation",
            target_id=holds[0].id,
            request=request,
        )
        db.commit()
    check_message_safety(db, message, profile, oracle)
    with database_errors_retryable(db):
        return _message_sent(db, profile, message), True


# The Oracle's reply


@dataclass(frozen=True)
class ReplyClaim:
    """The client message to answer, and when this request claimed it (None when its reply is
    already saved and only needs sending again)."""

    question: Message
    claimed_at: datetime | None


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _message_json(message: Message) -> dict:
    # mode="json" formats ids and times the same way as every other response.
    return MessageOut.model_validate(message).model_dump(mode="json")


def _history(messages: list[Message], question: Message) -> list[Message]:
    """The conversation up to and including the question, latest messages only: what the
    Oracle is given."""
    return messages[: messages.index(question) + 1][-settings.oracle_history_messages :]


def prepare_reply(
    db: Session, conversation: Conversation, account: User, oracle: Oracle
) -> ReplyClaim:
    """Checks the reply can be given and claims the message, before the stream starts, so a
    refusal is an ordinary JSON error."""
    with database_errors_retryable(db):
        entitlements.check_can_talk(account)
        profile = conversation.profile
        check_can_use(profile)
        messages = _messages(db, conversation)
        question = _last_client_message(messages)
        if question is None:  # can't happen: every conversation has a client message
            raise AppError(409, "nothing_to_reply_to", ACTION_FAILED)
        if _reply_to(messages, question) is not None:
            return ReplyClaim(question, None)  # reply_events sends the saved reply again
        db.commit()

    # Every client message the Oracle will read must have passed a safety check, not only the
    # last one: an earlier one may have failed its check when it was sent.
    for message in _history(messages, question):
        if message.role == "client" and message.safety_level is None:
            if check_message_safety(db, message, profile, oracle) is None:
                raise AppError(503, "safety_check_failed", ACTION_FAILED)

    with database_errors_retryable(db):
        # Story 3.2: no reply while an emergency or crisis waits for an option, including one
        # the checks above have just found.
        if safety.open_hold(db, conversation.id) is not None:
            raise _safety_hold_error()
        if not has_health_consent(db, profile):
            raise AppError(403, "health_consent_required", HEALTH_CONSENT_REQUIRED)
        if question.reply_attempts >= settings.reply_max_attempts:
            raise AppError(429, "too_many_attempts", TOO_MANY_ATTEMPTS)
        # Only one stream generates a reply at a time. A claim older than reply_claim_seconds
        # belongs to a stream that died, so it can be taken over.
        now = datetime.now(UTC)
        claimed_at = db.scalar(
            update(Message)
            .where(
                Message.id == question.id,
                or_(
                    Message.reply_started_at.is_(None),
                    Message.reply_started_at
                    < now - timedelta(seconds=settings.reply_claim_seconds),
                ),
            )
            .values(reply_started_at=now)
            .returning(Message.reply_started_at)
        )
        db.commit()
    if claimed_at is None:
        raise AppError(409, "reply_in_progress", REPLY_IN_PROGRESS)
    return ReplyClaim(question, claimed_at)


def _release_claim(db: Session, claim: ReplyClaim) -> None:
    """Lets the app try again straight away after a reply failed. Only this request's own
    claim is released: one that has since been taken over by another stream is left alone."""
    try:
        db.rollback()
        db.execute(
            update(Message)
            .where(
                Message.id == claim.question.id,
                Message.reply_started_at == claim.claimed_at,
            )
            .values(reply_started_at=None)
        )
        db.commit()
    except Exception:  # the claim expires on its own after reply_claim_seconds
        db.rollback()


def _earlier_conversations(
    db: Session, profile: Profile, current: Conversation
) -> list[EarlierConversation]:
    """The profile's most recent other conversations, each with its latest messages. Ones the
    client deleted aren't used."""
    conversations = db.scalars(
        select(Conversation)
        .where(
            Conversation.profile_id == profile.id,
            Conversation.id != current.id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.last_message_at.desc())
        .limit(settings.oracle_earlier_conversations)
    ).all()
    earlier = []
    for conversation in conversations:
        latest = db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(settings.oracle_earlier_messages)
        ).all()
        earlier.append(
            EarlierConversation(
                topic=conversation.topic,
                last_message_at=conversation.last_message_at,
                turns=[_turn(message) for message in reversed(latest)],
            )
        )
    return earlier


def reply_events(
    db: Session,
    conversation: Conversation,
    claim: ReplyClaim,
    account: User,
    oracle: Oracle,
) -> Iterator[str]:
    """Server-sent events: "delta" with each piece of text as it's generated, "widget" with
    each structured part, then "done" with the saved message, or "error" if the reply couldn't
    be finished. A reply that was already saved is sent as one delta (and its widgets).

    The router runs this in the thread pool and closes it there, including when the client
    disconnects, so its cleanup never blocks the event loop."""
    messages = _messages(db, conversation)
    saved = _reply_to(messages, claim.question)
    if saved is not None:
        yield _event("delta", {"text": saved.text})
        for widget in saved.widgets or []:
            yield _event("widget", {"widget": widget})
        yield _event("done", {"message": _message_json(saved)})
        return

    if not _reply_streams.acquire(blocking=False):
        _release_claim(db, claim)  # not counted as an attempt: the Oracle wasn't asked
        yield _event("error", {"code": "busy", "message": ACTION_FAILED})
        return
    try:
        yield from _generate_reply(db, conversation, claim, messages, account, oracle)
    finally:
        _reply_streams.release()


def _generate_reply(
    db: Session,
    conversation: Conversation,
    claim: ReplyClaim,
    messages: list[Message],
    account: User,
    oracle: Oracle,
) -> Iterator[str]:
    question = claim.question
    profile = conversation.profile
    pieces: list[str] = []
    widgets: list[Widget] = []
    facts: list[Widget] = []  # health details, saved with the reply and never streamed
    stream = None
    try:
        # An attempt counts from here, when the Oracle is about to be asked.
        db.execute(
            update(Message)
            .where(Message.id == question.id)
            .values(reply_attempts=Message.reply_attempts + 1)
        )
        # With the health profile (story 6.1), so nothing already answered is asked again.
        context = profile_context(profile, account, db)
        # Product links are for adults only (story 3.1), enforced here whatever the reply says.
        adult = is_adult(profile.date_of_birth)
        # Story 10.1: a teen with their own account doesn't see the consult card, and only a
        # message the safety check found safe can go to the support team (3.2 otherwise).
        teen_account = support_service.is_teen_account(account)
        offer_support = question.safety_level == "none"
        history = [_turn(message) for message in _history(messages, question)]
        earlier = _earlier_conversations(db, profile, conversation)
        db.commit()  # no transaction is held while the Oracle generates

        deadline = time.monotonic() + settings.reply_timeout_seconds
        stream = oracle.stream_reply(context, history, earlier)
        for piece in stream:
            if time.monotonic() > deadline:
                raise OracleError("The reply took too long.")
            if isinstance(piece, str):
                pieces.append(piece)
                yield _event("delta", {"text": piece})
            elif isinstance(piece, dict):
                widget = prepare_widget(
                    piece, adult=adult, teen_account=teen_account, offer_support=offer_support
                )
                if widget is None:
                    continue
                if widget.get("kind") == HEALTH_FACT:
                    facts.append(widget)  # saved with the reply (3.1), not shown in the chat
                    continue
                widgets.append(widget)
                yield _event("widget", {"widget": widget})
            else:
                raise OracleError("The reply contained something that isn't text or a widget.")
        text = "".join(pieces)
        if not text.strip():
            raise OracleError("The reply was empty.")
    except GeneratorExit:  # the client disconnected: free the message for its retry
        _release_claim(db, claim)
        raise
    except Exception as error:  # the AI service or the database failed; nothing is saved
        logger.warning(
            "Oracle reply failed: %s (conversation %s)", type(error).__name__, conversation.id
        )
        _release_claim(db, claim)
        yield _event("error", {"code": "reply_failed", "message": ACTION_FAILED})
        return
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()  # stops the Oracle's generation if the stream ended early

    topic = None
    if conversation.topic is None:
        try:
            topic = clean_line(oracle.topic(context, [*history, Turn(role="oracle", text=text)]))
        except Exception as error:  # only the list's label; the next reply tries again
            logger.warning(
                "Oracle topic failed: %s (conversation %s)", type(error).__name__, conversation.id
            )

    try:
        # The profile or the consent may have changed while the reply was generated, the client
        # may have deleted the conversation, and a message sent meanwhile may have opened a
        # safety hold: then the reply isn't saved into it.
        # Saving health details takes the profile lock, before the conversation's, in the
        # same order as sending a message and saving My Health.
        db.refresh(profile, with_for_update=bool(facts))
        check_can_use(profile)
        if not has_health_consent(db, profile):
            raise AppError(403, "health_consent_required", HEALTH_CONSENT_REQUIRED)
        db.refresh(conversation, with_for_update=True)  # held until the reply is saved
        if conversation.deleted_at is not None:
            raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
        if safety.open_hold(db, conversation.id) is not None:
            raise _safety_hold_error()
    except AppError as error:
        _release_claim(db, claim)
        yield _event("error", {"code": error.code, "message": error.message})
        return

    # The health details are saved in the reply's own transaction (so not without it), and the
    # one disclosure box goes last (story 3.1). It's streamed once the reply is saved, so what's
    # saved is still exactly what was streamed.
    tail: list[Widget] = []
    try:
        _save_health_details(db, conversation, account, facts)
        tail = closing_widgets(widgets)
        reply = Message(
            conversation_id=conversation.id,
            role="oracle",
            text=text,
            reply_to_id=question.id,
            widgets=[*widgets, *tail] or None,
        )
        db.add(reply)
        conversation.last_message_at = datetime.now(UTC)
        if topic:
            conversation.topic = topic[:TOPIC_MAX_LENGTH]
        db.commit()
    except IntegrityError:
        # Another stream saved a reply to the same message first (with its own details), or the
        # profile was deleted meanwhile. "done" then carries that saved reply.
        db.rollback()
        reply = _reply_to(_messages(db, conversation), question)
        tail = []
    except Exception as error:
        logger.warning(
            "Saving a reply failed: %s (conversation %s)", type(error).__name__, conversation.id
        )
        db.rollback()
        reply = None
    if reply is None:
        _release_claim(db, claim)
        yield _event("error", {"code": "reply_failed", "message": ACTION_FAILED})
        return
    for widget in tail:
        yield _event("widget", {"widget": widget})
    yield _event("done", {"message": _message_json(reply)})


def _save_health_details(
    db: Session, conversation: Conversation, account: User, details: list[Widget]
) -> int:
    """Stories 3.1, 3.3 and 6.1 (6 Nov 19:22): what the Oracle learned is saved to the health
    profile automatically, because the client accepted the Health Consent (checked just before),
    marked as added from this conversation (app.health.service.save_from_conversation). Saved
    during the free trial too. One that doesn't fit the profile's questions, or changes nothing,
    is dropped. Each is saved in a savepoint, so one that fails drops only itself. The change is
    logged once for the reply. Doesn't commit: the reply's save does, so nothing is saved
    without the reply. The values are health data: only the error's class is logged.

    The caller holds the profile lock. Returns how many answers were saved."""
    if not details:
        return 0
    profile = conversation.profile
    saved = 0
    try:
        # The details and their log go together: if the log fails, the details are dropped,
        # and the reply is still saved.
        with db.begin_nested():
            for detail in details[: settings.max_health_facts_per_reply]:
                try:
                    with db.begin_nested():
                        answer = health_service.save_from_conversation(
                            db,
                            profile,
                            account,
                            detail["question_key"],
                            detail["value"],
                            detail["other"],
                            conversation_id=conversation.id,
                        )
                except Exception as error:  # the Oracle's value can be any shape
                    logger.warning(
                        "Saving a health detail failed: %s (conversation %s)",
                        type(error).__name__,
                        conversation.id,
                    )
                    continue
                saved += answer is not None
            health_service.record_conversation_saves(db, profile, account, saved)
    except Exception as error:
        logger.warning(
            "Saving health details failed: %s (conversation %s)",
            type(error).__name__,
            conversation.id,
        )
        return 0
    return saved


# Sending to the support team from the conversation (story 10.1)


def _support_offer(db: Session, conversation: Conversation, body: RequestSupport) -> Message:
    """The Oracle reply whose offer the client accepted: a reply in this conversation that
    carries a support_offer of that kind. Anything else is a 404, so the Oracle, not the app,
    decides what counts as a knowledge gap."""
    offer = db.get(Message, body.message_id)
    if (
        offer is None
        or offer.conversation_id != conversation.id
        or offer.role != "oracle"
        or offer.reply_to_id is None
        or not any(
            widget.get("kind") == SUPPORT_OFFER and widget.get("request_kind") == body.kind
            for widget in offer.widgets or []
        )
    ):
        raise AppError(404, "support_offer_not_found", support_service.MESSAGE_NOT_FOUND)
    return offer


def _support_line(db: Session, conversation: Conversation, request_id: uuid.UUID) -> Message | None:
    """The confirmation line already saved for this request, if any."""
    return db.scalars(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "oracle",
            Message.widgets.contains(
                [{"kind": SUPPORT_REQUEST_SENT, "support_request_id": str(request_id)}]
            ),
        )
    ).first()


def request_support(
    db: Session,
    conversation: Conversation,
    body: RequestSupport,
    account: User,
    request: Request,
) -> tuple[SupportRequestFromConversation, bool]:
    """Story 10.1: the client agreed to send a question the Oracle couldn't answer (a knowledge
    gap) or their request for a person to the support team. The client message that the
    offer's reply answers is sent (app.support.service.create_from_conversation), and the
    story's "I’ve let the support team know..." is saved as an Oracle line, so it stays in the
    history and the Oracle knows it was sent. Both are committed together, with the request's
    team email job and audit event. Returns (result, created); safe to repeat.

    Refused during an emergency or crisis hold (story 3.2), and by the support package for a
    message the safety check didn't find safe, a profile that can't be used, or too many
    requests in an hour. A database error gets 10.1's "Sending failed" message."""
    profile = conversation.profile
    try:
        db.refresh(profile, with_for_update=True)  # the same lock order as sending a message
        db.refresh(conversation, with_for_update=True)
        if conversation.deleted_at is not None:
            raise AppError(404, "conversation_not_found", CONVERSATION_NOT_FOUND)
        if safety.open_hold(db, conversation.id) is not None:
            raise _safety_hold_error()
        offer = _support_offer(db, conversation, body)
        sent = support_service.create_from_conversation(
            db,
            account,
            profile,
            conversation.id,
            body.kind,
            message_id=offer.reply_to_id,
            request=request,
        )
        line = _support_line(db, conversation, sent.id)
        created = line is None
        if line is None:
            line = Message(
                conversation_id=conversation.id,
                role="oracle",
                text=sent.message,
                widgets=[support_request_sent(sent.id, body.kind, offer.id)],
            )
            db.add(line)
            conversation.last_message_at = datetime.now(UTC)
            db.flush()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "send_failed", support_service.SEND_FAILED) from None
    except AppError:
        db.rollback()  # lets go of the locks straight away
        raise
    result = SupportRequestFromConversation(
        support_request=sent, message=MessageOut.model_validate(line)
    )
    return result, created


# Feedback and deleting a conversation. Neither is in the 4 Nov stories; the assumptions are in
# docs/PLAN.md and wait for the BA.


def _oracle_message(db: Session, conversation: Conversation, message_id: uuid.UUID) -> Message:
    """One of the Oracle's replies in this conversation, or a 404."""
    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id or message.role != "oracle":
        raise AppError(404, "message_not_found", "We couldn’t find that message.")
    return message


def give_feedback(
    db: Session,
    conversation: Conversation,
    message_id: uuid.UUID,
    data: GiveFeedback,
    account: User,
    request: Request,
) -> FeedbackOut:
    """A thumbs up or down on a reply, replacing any earlier one. The audit event says which,
    and whether there's a comment, never what it says."""
    check_can_use(conversation.profile)
    message = _oracle_message(db, conversation, message_id)
    with database_errors_retryable(db):
        feedback = db.scalar(
            select(MessageFeedback).where(MessageFeedback.message_id == message.id)
        )
        if feedback is not None and (feedback.rating, feedback.comment) == (
            data.rating,
            data.comment,
        ):
            return FeedbackOut.model_validate(feedback)  # nothing changed: no write, no audit
        if feedback is None:
            feedback = MessageFeedback(message_id=message.id)
            db.add(feedback)
        feedback.given_by_id = account.id
        feedback.rating = data.rating
        feedback.comment = data.comment
        audit.record(
            db,
            "conversation.feedback_given",
            actor_id=account.id,
            target_type="message",
            target_id=message.id,
            request=request,
            details={"rating": data.rating, "comment": data.comment is not None},
        )
        # Two at once for the same reply: the second breaks the unique key, gets the 503,
        # and works when it's tried again.
        db.commit()
    return FeedbackOut.model_validate(feedback)


def remove_feedback(
    db: Session,
    conversation: Conversation,
    message_id: uuid.UUID,
    account: User,
    request: Request,
) -> None:
    """Takes a thumbs up or down back. Safe to repeat."""
    check_can_use(conversation.profile)
    message = _oracle_message(db, conversation, message_id)
    with database_errors_retryable(db):
        removed = db.execute(
            delete(MessageFeedback).where(MessageFeedback.message_id == message.id)
        ).rowcount
        if removed:
            audit.record(
                db,
                "conversation.feedback_removed",
                actor_id=account.id,
                target_type="message",
                target_id=message.id,
                request=request,
            )
        db.commit()


def delete_conversation(
    db: Session, conversation: Conversation, account: User, oracle: Oracle, request: Request
) -> None:
    """Removes the conversation from the client's lists at once, and stops the Oracle using
    it in other conversations. The messages stay until Phase 10's purge; its escalations
    (story 3.2) are kept for 6 years in any case, since nothing deletes them with it.

    Refused while an emergency or crisis hold is open (story 3.2), and so also while a
    message's safety check is still to come, which could open one: those checks run here
    first, with no lock held, as in the reply step.

    Deleting isn't using the profile, so it works for a turned-off family member too, whose
    conversations can still be read."""
    profile = conversation.profile
    try:
        unchecked = _unchecked_messages(db, conversation)
        db.commit()  # no transaction is held while the Oracle checks
        for message in unchecked:
            if check_message_safety(db, message, profile, oracle) is None:
                raise AppError(503, "safety_check_failed", DELETE_FAILED)
        # The same lock as sending a message and saving a reply, so neither lands after this.
        db.refresh(conversation, with_for_update=True)
        if _unchecked_messages(db, conversation):
            # Sent since the checks above: trying again checks it too.
            raise AppError(503, "safety_check_failed", DELETE_FAILED)
        if safety.open_hold(db, conversation.id) is not None:
            raise _safety_hold_error()
        conversation.deleted_at = datetime.now(UTC)
        audit.record(
            db,
            "conversation.deleted",
            actor_id=account.id,
            target_type="conversation",
            target_id=conversation.id,
            request=request,
        )
        # Phase 5 (question 45): its summary and notes go with it, so their reminders stop.
        # Imported here: app.guidance imports this module.
        from app.guidance import reminders

        reminders.conversation_deleted(db, conversation, account)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", DELETE_FAILED) from None
    except AppError:
        db.rollback()  # lets go of the conversation's lock straight away
        raise
