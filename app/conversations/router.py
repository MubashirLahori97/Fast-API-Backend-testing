import uuid
from collections.abc import AsyncIterator, Iterator

import anyio
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.accounts.dependencies import ClientSession, consented_session
from app.accounts.schemas import PolicyOut
from app.conversations import service
from app.conversations.dependencies import OwnedConversation
from app.conversations.schemas import (
    AcceptHealthConsent,
    ChooseSafetyOption,
    ConversationOut,
    ConversationSummary,
    FeedbackOut,
    GiveFeedback,
    HealthConsentOut,
    MessageSent,
    NewConversation,
    RequestSupport,
    SendMessage,
    SupportRequestFromConversation,
)
from app.core.database import DbSession
from app.oracle.dependencies import OracleService
from app.profiles.dependencies import OwnedProfile, UsableProfile

# The policy gate applies to every route here, including ones added later.
router = APIRouter(tags=["conversations"], dependencies=[Depends(consented_session)])


@router.get("/profiles/{profile_id}/conversations")
def list_conversations(profile: OwnedProfile, db: DbSession) -> list[ConversationSummary]:
    """Story 3.1: the profile's conversations, most recent first."""
    return service.list_conversations(db, profile)


@router.get("/profiles/{profile_id}/conversations/new")
def new_conversation(profile: UsableProfile, session: ClientSession) -> NewConversation:
    """Story 3.1: the New Conversation screen's opening question and starter questions."""
    return service.new_conversation(profile, session.user)


@router.post("/profiles/{profile_id}/conversations", status_code=201)
def start_conversation(
    body: SendMessage,
    profile: UsableProfile,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    response: Response,
    db: DbSession,
) -> MessageSent:
    """Story 3.1: starts a conversation with the client's first message. Answers 200 with the
    saved message when it's a resend."""
    result, created = service.start_conversation(db, profile, body, session.user, oracle, request)
    if not created:
        response.status_code = 200
    return result


@router.get("/profiles/{profile_id}/health-consent")
def get_health_consent(profile: OwnedProfile, db: DbSession) -> HealthConsentOut:
    """Story 3.1: whether the current Health Consent is accepted for this profile."""
    policy = service.current_health_consent(db)
    return HealthConsentOut(
        accepted=service.has_health_consent(db, profile),
        policy=PolicyOut.model_validate(policy),
    )


@router.post("/profiles/{profile_id}/health-consent")
def accept_health_consent(
    body: AcceptHealthConsent,
    profile: UsableProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> HealthConsentOut:
    """Story 3.1 "Agree and continue": accepts the current Health Consent for this profile."""
    service.accept_health_consent(db, profile, body.policy_version_id, session.user, request)
    return get_health_consent(profile, db)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation: OwnedConversation, session: ClientSession, db: DbSession
) -> ConversationOut:
    """Story 3.1: a conversation with its full history."""
    return service.conversation_out(db, conversation, session.user)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    db: DbSession,
) -> Response:
    """Not in the 4 Nov stories (docs/PLAN.md): removes the conversation from the client's
    lists straight away. After that it answers 404, like any unknown conversation. Refused
    with 409 `safety_hold` while an emergency or crisis waits for an option (story 3.2)."""
    service.delete_conversation(db, conversation, session.user, oracle, request)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/safety-choice", status_code=201)
def choose_safety_option(
    body: ChooseSafetyOption,
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    request: Request,
    response: Response,
    db: DbSession,
) -> MessageSent:
    """Story 3.2: the option the client picked on the emergency or crisis screen. It ends the
    hold, and is saved as the client's next message; `next` then says what to show. Answers
    200 with the saved message when it's a resend, and 409 `no_safety_hold` when there's no
    hold to answer."""
    result, created = service.choose_safety_option(
        db, conversation, body, session.user, oracle, request
    )
    if not created:
        response.status_code = 200
    return result


@router.post("/conversations/{conversation_id}/support-request", status_code=201)
def request_support(
    body: RequestSupport,
    conversation: OwnedConversation,
    session: ClientSession,
    request: Request,
    response: Response,
    db: DbSession,
) -> SupportRequestFromConversation:
    """Story 10.1: the client tapped Yes on the Oracle's offer (a `support_offer` card) to send
    a question it couldn't answer (`knowledge_gap`) or their request for a person
    (`talk_to_support`) to the support team. Answers with the request and the Oracle line
    "I’ve let the support team know...", now in the conversation; 200 when the same offer was
    already sent. 409 `safety_hold` during an emergency or crisis hold, 409 `not_sendable` for a
    message the safety check didn't find safe, 404 for an unknown offer, 503 `send_failed` when
    it couldn't be saved."""
    result, created = service.request_support(db, conversation, body, session.user, request)
    if not created:
        response.status_code = 200
    return result


@router.put("/conversations/{conversation_id}/messages/{message_id}/feedback")
def give_feedback(
    message_id: uuid.UUID,
    body: GiveFeedback,
    conversation: OwnedConversation,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> FeedbackOut:
    """Not in the 4 Nov stories (docs/PLAN.md): a thumbs up or down on one of the Oracle's
    replies, with an optional comment. Sending it again replaces it."""
    return service.give_feedback(db, conversation, message_id, body, session.user, request)


@router.delete("/conversations/{conversation_id}/messages/{message_id}/feedback", status_code=204)
def remove_feedback(
    message_id: uuid.UUID,
    conversation: OwnedConversation,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> Response:
    """Takes a thumbs up or down back. Answers 204 whether or not there was one."""
    service.remove_feedback(db, conversation, message_id, session.user, request)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(
    body: SendMessage,
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    response: Response,
    db: DbSession,
) -> MessageSent:
    """Story 3.1: adds the client's message. Answers 200 with the saved message when it's a
    resend."""
    result, created = service.send_message(db, conversation, body, session.user, oracle)
    if not created:
        response.status_code = 200
    return result


async def _in_thread_pool(events: Iterator[str]) -> AsyncIterator[str]:
    """Runs the reply's generator in the thread pool, and closes it there too, including when
    the client disconnects. Its cleanup (releasing the claim, closing the Oracle's stream)
    then never runs on the event loop, and runs while the request's session is still open."""
    try:
        async for event in iterate_in_threadpool(events):
            yield event
    finally:
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(events.close)


@router.post(
    "/conversations/{conversation_id}/reply",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def reply(
    conversation: OwnedConversation,
    session: ClientSession,
    oracle: OracleService,
    db: DbSession,
) -> StreamingResponse:
    """Story 3.1: streams the Oracle's reply to the last client message as server-sent
    events: "delta" pieces of text and "widget" parts, then "done" or "error". Ask again after
    a lost connection."""
    claim = service.prepare_reply(db, conversation, session.user, oracle)
    return StreamingResponse(
        _in_thread_pool(service.reply_events(db, conversation, claim, session.user, oracle)),
        media_type="text/event-stream",
        # Stops proxies such as nginx from holding the stream back until it ends.
        headers={"X-Accel-Buffering": "no"},
    )
