"""Conversations with the Oracle and the Health Consent (story 3.1), and the safety path
(story 3.2)."""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.accounts.schemas import PolicyOut
from app.core.config import settings
from app.core.schemas import RequestBody, clean_message
from app.oracle.contract import SupportRequestKind
from app.support.schemas import SupportRequestSent

ANSWER_MAX_LENGTH = 2000  # characters of JSON

EscalationLevel = Literal["urgent", "emergency", "crisis"]
HoldLevel = Literal["emergency", "crisis"]
SafetyOption = Literal["called_for_help", "reached_out", "safe_now"]


class SendMessage(RequestBody):
    """A client message. The app makes `client_msg_id` (a UUID) once per message and sends it
    again with any retry, so a message is never saved twice. Symptoms ticked in the symptom
    check arrive as part of the text. A tapped answer sends its label as the text, and what
    was tapped as `answer` (see Answer in app/oracle/contract.py).

    `outside_us` is true when the device's location shows the client is outside the US (story
    3.2): the safety advice then gives the local emergency number instead of 911 and 988. Leave
    it out when the location is unknown, and the US numbers are shown."""

    client_msg_id: uuid.UUID
    text: str = Field(default="", max_length=settings.message_max_length)
    answer: dict[str, Any] | None = None
    outside_us: bool = False

    @field_validator("text", mode="before")
    @classmethod
    def check_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = clean_message(value)
        if not value:
            raise ValueError("Please type a message to send.")
        if len(value) > settings.message_max_length:
            raise ValueError(
                f"That message is too long. Please keep it to "
                f"{settings.message_max_length:,} characters or fewer."
            )
        return value

    @field_validator("answer")
    @classmethod
    def check_answer(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        value = _clean_strings(value)
        if len(json.dumps(value)) > ANSWER_MAX_LENGTH:
            raise ValueError("That answer is too long to save.")
        return value


def _clean_strings(value: Any) -> Any:
    """Every string inside an answer, keys included, cleaned like message text. Postgres can't
    store NUL in JSON either."""
    if isinstance(value, str):
        return clean_message(value)
    if isinstance(value, dict):
        return {clean_message(str(key)): _clean_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_strings(item) for item in value]
    return value


class ChooseSafetyOption(RequestBody):
    """Story 3.2: the option the client picked on the emergency or crisis screen: "I’ve called
    for help" (`called_for_help`, emergency) or "I’ve reached out for help" (`reached_out`,
    crisis), or "I’m safe now" (`safe_now`). It's saved as the client's next message, so
    `client_msg_id` works as it does for any message."""

    client_msg_id: uuid.UUID
    # Checked against the hold's level by the service, which answers 3.2's "Please let me know
    # you’re safe before we continue." for a missing or wrong option.
    option: str | None = None


class RequestSupport(RequestBody):
    """Story 10.1: the client tapped Yes on the Oracle's offer to send something to the support
    team (a `support_offer` card). `message_id` is the Oracle reply with the offer, and `kind`
    the offer's `request_kind`: `knowledge_gap` (a question the Oracle couldn't answer) or
    `talk_to_support` (the client asked for a person). The client message that reply answers
    is what's sent. Safe to repeat: the same offer sends one request.

    "Consult with support team" isn't sent here: its card opens 10.1's Consult form, which goes
    to POST /profiles/{id}/support-requests with kind `consultation`."""

    kind: SupportRequestKind
    message_id: uuid.UUID


class AcceptHealthConsent(RequestBody):
    """The Health Consent version the client was shown and accepted."""

    policy_version_id: uuid.UUID | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["client", "oracle"]
    text: str
    client_msg_id: uuid.UUID | None  # client messages
    answer: dict[str, Any] | None  # client messages: what they tapped, if anything
    widgets: list[dict[str, Any]] | None  # Oracle messages: options and cards to show
    created_at: datetime
    # Oracle messages: the client's thumbs up or down, if they gave one.
    feedback: Literal["up", "down"] | None = None
    # Oracle messages: set on the backend's safety advice (story 3.2), so the app can show it
    # as the urgent, emergency or crisis message.
    safety: EscalationLevel | None = None


class SafetyOptionOut(BaseModel):
    option: SafetyOption
    label: str  # "I’ve called for help", "I’ve reached out for help" or "I’m safe now"


class SafetyHoldOut(BaseModel):
    """An open emergency or crisis hold (story 3.2): the conversation is paused, and no reply is
    given, until the client picks one of the options (POST .../safety-choice). Messages sent
    meanwhile are saved and checked, but get no reply."""

    level: HoldLevel
    message_id: uuid.UUID  # the Oracle line with the advice, in the conversation's history
    text: str  # that advice: 911 or 988, or the local emergency number outside the US
    options: list[SafetyOptionOut]
    # 3.2's "Option not selected": for the app to show if the client tries to carry on first.
    reminder: str


class SafetyAdviceOut(BaseModel):
    """What the safety check found in the message just sent (story 3.2), and the advice line
    the backend added to the conversation for it, to show straight away."""

    level: EscalationLevel
    message: MessageOut


class GiveFeedback(RequestBody):
    """A thumbs up or down on one of the Oracle's replies, with an optional comment. Giving
    it again replaces the earlier one."""

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=settings.feedback_comment_max_length)

    @field_validator("comment")
    @classmethod
    def check_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_message(value) or None  # an empty comment is no comment


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    rating: Literal["up", "down"]
    comment: str | None


class MessageSent(BaseModel):
    conversation_id: uuid.UUID
    message: MessageOut
    # What the app does next:
    # - "safety_hold": show the emergency or crisis screen in `safety_hold` (story 3.2). It
    #   comes before the Health Consent, and no reply is given until an option is picked;
    # - "reply": ask for the Oracle's reply (POST .../reply);
    # - "health_consent": show the Health Consent first (story 3.1);
    # - "send_again": every reply attempt failed, so the app offers to send the text again as a
    #   new message, with a new client_msg_id.
    next: Literal["safety_hold", "reply", "health_consent", "send_again"]
    # The safety advice for this message, if its check found an urgent, emergency or crisis
    # concern. Urgent advice is shown, and the conversation carries on.
    safety: SafetyAdviceOut | None = None
    # The conversation's open hold, if any (it may come from an earlier message).
    safety_hold: SafetyHoldOut | None = None


class SupportRequestFromConversation(BaseModel):
    """A request sent from the conversation (story 10.1)."""

    support_request: SupportRequestSent
    # The Oracle line saved in the conversation: "I’ve let the support team know. They’ll get
    # back to you by email within one business day.", with a `support_request_sent` widget
    # naming the request and the offer it answers.
    message: MessageOut


class ConversationSummary(BaseModel):
    """A row in the conversation list: "Waking at 3am · 3 days ago"."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str | None  # null until the Oracle's first reply
    created_at: datetime
    last_message_at: datetime
    # Paused by an emergency or crisis until the client picks an option (story 3.2).
    safety_hold: bool = False


class ConversationOut(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    topic: str | None
    created_at: datetime
    last_message_at: datetime
    messages: list[MessageOut]  # the full history, oldest first
    # The last client message has no reply yet, for example after a lost connection: the app
    # asks for it again with POST .../reply. Never true during a safety hold.
    awaiting_reply: bool
    # Story 3.1's "Welcome back, [First Name]. Last time we talked about [topic]. ..." when the
    # conversation is picked up after a while. The app shows it as the Oracle's next line; it's
    # saved into the conversation when the client sends their next message. Not during a hold.
    welcome_back: str | None
    # Story 3.2: an open emergency or crisis hold. The app shows its screen, and offers its
    # options, before anything else.
    safety_hold: SafetyHoldOut | None


class NewConversation(BaseModel):
    """The New Conversation screen (story 3.1)."""

    opening: str  # "How are you feeling today?" / "How is [Name] feeling today?"
    starters: list[str]  # suggested first questions (app/conversations/starters.py)


class HealthConsentOut(BaseModel):
    accepted: bool  # the current version is accepted for this profile
    policy: PolicyOut  # the current version, for the link to the full document
