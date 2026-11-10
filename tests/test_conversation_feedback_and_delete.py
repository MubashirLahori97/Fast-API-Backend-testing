"""Feedback on the Oracle's replies, and deleting a conversation.

Neither is in the 4 Nov stories: both were built on the user's request after comparing with
the team's API. The assumptions, including the "We couldn’t find that message." wording, are in
docs/PLAN.md ("Message feedback and deleting conversations", open questions 44 and 45).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.conversations import service
from app.conversations.models import Conversation, Message, MessageFeedback
from app.conversations.schemas import SendMessage
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.errors import AppError
from tests.helpers import bearer
from tests.test_conversations import (
    BEING_DELETED,
    CONVERSATION_NOT_FOUND,
    FIRST_MESSAGE,
    OPENING,
    TURNED_OFF,
    ChangesMidReply,
    accept_consent,
    answered,
    audit_events,
    listed_ids,
    marias_headers,
    open_conversation,
    reply,
    send,
    sse,
    start,
    started,
    use_oracle,
)
from tests.test_intake_family import add_member
from tests.test_manage_family import own_profile_id, remove, turn_off

MESSAGE_NOT_FOUND = {
    "code": "message_not_found",
    "message": "We couldn’t find that message.",
    "field": None,
}
KNEES = "My knees ache in the morning."


@pytest.fixture
def user(make_user):
    """Sarah, on the Basic plan so she can add family members, with her own profile done."""
    return make_user(subscription_plan="basic")


@pytest.fixture
def headers(user, sign_in) -> dict[str, str]:
    return bearer(sign_in()["access_token"])


@pytest.fixture
def own_id(client, headers) -> str:
    return own_profile_id(client, headers)


@pytest.fixture
def azka(client, headers) -> str:
    """A finished family member, Azka (child, 9)."""
    return add_member(client, headers)


@pytest.fixture
def conversation_id(client, headers, own_id) -> str:
    """Sarah's conversation: the opening question, her first message and the Oracle's reply."""
    return answered(client, headers, own_id)


@pytest.fixture
def reply_id(client, headers, conversation_id) -> str:
    return oracle_reply_id(client, headers, conversation_id)


def oracle_reply_id(client, headers, conversation_id) -> str:
    """The Oracle's latest message in the conversation."""
    messages = open_conversation(client, headers, conversation_id)["messages"]
    return [message["id"] for message in messages if message["role"] == "oracle"][-1]


def feedback_path(conversation_id, message_id) -> str:
    return f"/conversations/{conversation_id}/messages/{message_id}/feedback"


def rate(client, headers, conversation_id, message_id, **body):
    return client.put(feedback_path(conversation_id, message_id), headers=headers, json=body)


def unrate(client, headers, conversation_id, message_id):
    return client.delete(feedback_path(conversation_id, message_id), headers=headers)


def give_or_remove(action, client, headers, conversation_id, message_id):
    if action == "give":
        return rate(client, headers, conversation_id, message_id, rating="up")
    return unrate(client, headers, conversation_id, message_id)


def delete(client, headers, conversation_id):
    return client.delete(f"/conversations/{conversation_id}", headers=headers)


def saved_feedback(db) -> list[tuple[str, str | None]]:
    rows = db.scalars(select(MessageFeedback).execution_options(populate_existing=True))
    return [(row.rating, row.comment) for row in rows]


# Giving feedback on a reply


def test_feedback_on_a_reply_is_saved(client, db, headers, conversation_id, reply_id):
    response = rate(client, headers, conversation_id, reply_id, rating="up")

    assert response.status_code == 200
    assert response.json() == {"message_id": reply_id, "rating": "up", "comment": None}
    assert saved_feedback(db) == [("up", None)]


def test_feedback_can_have_a_comment(client, db, headers, conversation_id, reply_id):
    response = rate(
        client, headers, conversation_id, reply_id, rating="down", comment="It missed my question."
    )

    assert response.status_code == 200
    assert response.json()["comment"] == "It missed my question."
    assert saved_feedback(db) == [("down", "It missed my question.")]


def test_feedback_comment_is_cleaned(client, headers, conversation_id, reply_id):
    response = rate(
        client,
        headers,
        conversation_id,
        reply_id,
        rating="down",
        comment="  Too vague.\x07\r\nSecond line.  ",
    )

    assert response.json()["comment"] == "Too vague.\nSecond line."


@pytest.mark.parametrize("comment", ["", "   ", "\n\t"], ids=["empty", "spaces", "line-break"])
def test_empty_comment_is_no_comment(client, db, headers, conversation_id, reply_id, comment):
    response = rate(client, headers, conversation_id, reply_id, rating="up", comment=comment)

    assert response.json()["comment"] is None
    assert saved_feedback(db) == [("up", None)]


def test_giving_feedback_again_replaces_it(client, db, headers, conversation_id, reply_id):
    rate(client, headers, conversation_id, reply_id, rating="up", comment="Helpful.")

    response = rate(client, headers, conversation_id, reply_id, rating="down")

    assert response.json() == {"message_id": reply_id, "rating": "down", "comment": None}
    assert saved_feedback(db) == [("down", None)]


def test_giving_the_same_feedback_again_records_nothing_new(
    client, db, headers, conversation_id, reply_id
):
    rate(client, headers, conversation_id, reply_id, rating="down", comment="Too vague.")

    response = rate(client, headers, conversation_id, reply_id, rating="down", comment="Too vague.")

    assert response.status_code == 200
    assert response.json() == {"message_id": reply_id, "rating": "down", "comment": "Too vague."}
    assert len(audit_events(db, "conversation.feedback_given")) == 1


def test_conversation_shows_the_feedback_on_each_message(
    client, headers, conversation_id, reply_id
):
    rate(client, headers, conversation_id, reply_id, rating="up")

    messages = open_conversation(client, headers, conversation_id)["messages"]

    assert [(message["role"], message["feedback"]) for message in messages] == [
        ("oracle", None),
        ("client", None),
        ("oracle", "up"),
    ]


def test_feedback_on_one_reply_leaves_the_others_alone(client, headers, conversation_id, reply_id):
    rate(client, headers, conversation_id, reply_id, rating="up")
    send(client, headers, conversation_id)
    reply(client, headers, conversation_id)

    messages = open_conversation(client, headers, conversation_id)["messages"]

    assert [message["feedback"] for message in messages if message["role"] == "oracle"] == [
        None,
        "up",
        None,
    ]


# Only the Oracle's messages in that conversation can be rated


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_on_a_client_message_is_not_found(
    client, headers, conversation_id, reply_id, action
):
    messages = open_conversation(client, headers, conversation_id)["messages"]
    client_message_id = next(message["id"] for message in messages if message["role"] == "client")

    response = give_or_remove(action, client, headers, conversation_id, client_message_id)

    assert response.status_code == 404
    assert response.json()["error"] == MESSAGE_NOT_FOUND


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_on_another_conversations_reply_is_not_found(
    client, headers, own_id, reply_id, action
):
    other = answered(client, headers, own_id, KNEES)

    response = give_or_remove(action, client, headers, other, reply_id)

    assert response.status_code == 404
    assert response.json()["error"] == MESSAGE_NOT_FOUND


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_on_an_unknown_message_is_not_found(client, headers, conversation_id, action):
    response = give_or_remove(action, client, headers, conversation_id, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"] == MESSAGE_NOT_FOUND


def test_refused_feedback_saves_nothing(client, db, headers, own_id, reply_id):
    other = answered(client, headers, own_id, KNEES)

    rate(client, headers, other, reply_id, rating="up")

    assert saved_feedback(db) == []


# Other refusals


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_on_another_accounts_conversation_is_not_found(
    client, make_user, sign_in, headers, conversation_id, reply_id, action
):
    rate(client, headers, conversation_id, reply_id, rating="up")
    marias = marias_headers(make_user, sign_in)

    response = give_or_remove(action, client, marias, conversation_id, reply_id)

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND
    assert open_conversation(client, headers, conversation_id)["messages"][-1]["feedback"] == "up"


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_for_a_turned_off_member_is_refused(client, headers, azka, action):
    conversation_id = answered(client, headers, azka, "Azka has stomach aches.")
    reply_id = oracle_reply_id(client, headers, conversation_id)
    turn_off(client, headers, azka)

    response = give_or_remove(action, client, headers, conversation_id, reply_id)

    assert response.status_code == 409
    assert response.json()["error"] == TURNED_OFF


@pytest.mark.parametrize("action", ["give", "remove"])
def test_feedback_for_a_member_being_deleted_is_refused(client, headers, azka, action):
    conversation_id = answered(client, headers, azka, "Azka has stomach aches.")
    reply_id = oracle_reply_id(client, headers, conversation_id)
    remove(client, headers, azka)

    response = give_or_remove(action, client, headers, conversation_id, reply_id)

    assert response.status_code == 409
    assert response.json()["error"] == BEING_DELETED


@pytest.mark.parametrize(
    "body",
    [{"rating": "sideways"}, {"rating": "UP"}, {"rating": ""}, {"rating": None}, {}],
    ids=["unknown", "uppercase", "empty", "null", "missing"],
)
def test_feedback_needs_up_or_down(client, db, headers, conversation_id, reply_id, body):
    response = client.put(feedback_path(conversation_id, reply_id), headers=headers, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "rating"
    assert saved_feedback(db) == []


def test_comment_over_2000_characters_is_refused(client, db, headers, conversation_id, reply_id):
    too_long = "x" * (settings.feedback_comment_max_length + 1)

    response = rate(client, headers, conversation_id, reply_id, rating="down", comment=too_long)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "comment"
    assert saved_feedback(db) == []


def test_comment_of_2000_characters_is_accepted(client, headers, conversation_id, reply_id):
    longest = "x" * settings.feedback_comment_max_length

    response = rate(client, headers, conversation_id, reply_id, rating="down", comment=longest)

    assert response.status_code == 200
    assert response.json()["comment"] == longest


def test_feedback_rejects_fields_clients_may_not_set(
    client, db, user, headers, conversation_id, reply_id
):
    response = rate(
        client, headers, conversation_id, reply_id, rating="up", given_by_id=str(uuid.uuid4())
    )

    assert response.status_code == 422
    assert saved_feedback(db) == []


# Record keeping: the rating and whether there's a comment, never the comment


@pytest.mark.parametrize(
    ("comment", "has_comment"), [(None, False), ("Too vague.", True)], ids=["none", "comment"]
)
def test_giving_feedback_is_audited(
    client, db, user, headers, conversation_id, reply_id, comment, has_comment
):
    body = {"rating": "down"} if comment is None else {"rating": "down", "comment": comment}

    rate(client, headers, conversation_id, reply_id, **body)

    [event] = audit_events(db, "conversation.feedback_given")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        user.id,
        "message",
        reply_id,
        {"rating": "down", "comment": has_comment},
    )


def test_feedback_comment_never_reaches_the_audit_log(
    client, db, headers, conversation_id, reply_id
):
    rate(
        client,
        headers,
        conversation_id,
        reply_id,
        rating="down",
        comment="My migraines got worse on the new tablets.",
    )
    unrate(client, headers, conversation_id, reply_id)

    for event in db.scalars(select(AuditEvent)):
        assert "migraines" not in json.dumps([event.details, event.target_id, event.user_agent])


# Taking feedback back


def test_removing_feedback(client, db, headers, conversation_id, reply_id):
    rate(client, headers, conversation_id, reply_id, rating="up")

    response = unrate(client, headers, conversation_id, reply_id)

    assert response.status_code == 204
    assert saved_feedback(db) == []
    assert open_conversation(client, headers, conversation_id)["messages"][-1]["feedback"] is None


def test_removing_feedback_again_is_fine(client, headers, conversation_id, reply_id):
    rate(client, headers, conversation_id, reply_id, rating="up")
    unrate(client, headers, conversation_id, reply_id)

    response = unrate(client, headers, conversation_id, reply_id)

    assert response.status_code == 204


def test_removing_feedback_is_audited_once(client, db, user, headers, conversation_id, reply_id):
    rate(client, headers, conversation_id, reply_id, rating="up")
    unrate(client, headers, conversation_id, reply_id)
    unrate(client, headers, conversation_id, reply_id)

    events = audit_events(db, "conversation.feedback_removed")

    assert [(event.actor_id, event.target_type, event.target_id) for event in events] == [
        (user.id, "message", reply_id)
    ]


def test_removing_feedback_that_was_never_given_records_nothing(
    client, db, headers, conversation_id, reply_id
):
    response = unrate(client, headers, conversation_id, reply_id)

    assert response.status_code == 204
    assert audit_events(db, "conversation.feedback_removed") == []


# Deleting a conversation


def test_deleting_a_conversation(client, db, headers, conversation_id):
    response = delete(client, headers, conversation_id)

    assert response.status_code == 204
    conversation = db.get(Conversation, uuid.UUID(conversation_id))
    db.refresh(conversation)
    assert abs(conversation.deleted_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_deleting_a_conversation_is_audited(client, db, user, headers, conversation_id):
    delete(client, headers, conversation_id)

    [event] = audit_events(db, "conversation.deleted")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        user.id,
        "conversation",
        conversation_id,
        {},
    )


def failing_commit():
    raise OperationalError("COMMIT", None, ConnectionError("database is down"))


def test_conversation_that_cant_be_deleted(
    client, db, headers, own_id, conversation_id, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", failing_commit)
        response = delete(client, headers, conversation_id)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "save_failed",
        "message": "We couldn’t delete this conversation just now. Please try again.",
        "field": None,
    }
    assert listed_ids(client, headers, own_id) == [conversation_id]


def test_conversation_deleted_while_the_reply_streams(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    def delete_it():
        db.get(Conversation, uuid.UUID(conversation_id)).deleted_at = datetime.now(UTC)
        db.commit()

    use_oracle(ChangesMidReply(delete_it))

    found = sse(reply(client, headers, conversation_id))

    assert found[-1] == (
        "error",
        {"code": "conversation_not_found", "message": CONVERSATION_NOT_FOUND["message"]},
    )
    oracle_messages = db.scalars(
        select(Message.text).where(
            Message.conversation_id == uuid.UUID(conversation_id), Message.role == "oracle"
        )
    ).all()
    assert oracle_messages == [OPENING]  # the reply wasn't saved


def test_message_to_a_conversation_deleted_meanwhile_is_refused(
    client, db, user, headers, own_id, oracle
):
    """A delete on another device after this request looked the conversation up. Through the
    API, OwnedConversation would answer 404 first, so the service is called directly."""
    conversation = db.get(Conversation, uuid.UUID(started(client, headers, own_id)))
    conversation.deleted_at = datetime.now(UTC)
    db.commit()
    body = SendMessage(client_msg_id=uuid.uuid4(), text="It started last month.")

    with pytest.raises(AppError) as refused:
        service.send_message(db, conversation, body, user, oracle)

    error = refused.value
    assert (error.status_code, error.code, error.message) == (
        404,
        "conversation_not_found",
        CONVERSATION_NOT_FOUND["message"],
    )
    db.rollback()
    saved = db.scalars(select(Message.text).where(Message.role == "client")).all()
    assert saved == [FIRST_MESSAGE]


def test_deleted_conversations_messages_are_kept(client, db, headers, conversation_id):
    """Until Phase 10's purge (docs/PLAN.md, open question 27)."""
    delete(client, headers, conversation_id)

    kept = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == uuid.UUID(conversation_id))
    )
    assert kept == 3


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/conversations/{cid}"),
        ("delete", "/conversations/{cid}"),
        ("post", "/conversations/{cid}/messages"),
        ("post", "/conversations/{cid}/reply"),
        ("put", "/conversations/{cid}/messages/{mid}/feedback"),
        ("delete", "/conversations/{cid}/messages/{mid}/feedback"),
    ],
)
def test_deleted_conversation_is_not_found(
    client, headers, conversation_id, reply_id, method, path
):
    delete(client, headers, conversation_id)
    body = None
    if path.endswith("/messages"):
        body = {"client_msg_id": str(uuid.uuid4()), "text": "It started last month."}
    elif method == "put":
        body = {"rating": "up"}

    response = client.request(
        method, path.format(cid=conversation_id, mid=reply_id), headers=headers, json=body
    )

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND


def test_deleted_conversation_leaves_the_list(client, headers, own_id, conversation_id):
    kept = answered(client, headers, own_id, KNEES)

    delete(client, headers, conversation_id)

    assert listed_ids(client, headers, own_id) == [kept]


def test_deleted_conversation_is_not_given_to_the_oracle(client, headers, own_id, oracle):
    deleted = answered(client, headers, own_id, FIRST_MESSAGE)
    answered(client, headers, own_id, KNEES)
    delete(client, headers, deleted)
    latest = started(client, headers, own_id, "I get headaches at work.")

    reply(client, headers, latest)

    earlier_texts = [turn.text for earlier in oracle.last_earlier for turn in earlier.turns]
    assert KNEES in earlier_texts
    assert FIRST_MESSAGE not in earlier_texts


def test_deleted_conversations_messages_count_towards_the_message_limit(
    client, headers, own_id, monkeypatch
):
    monkeypatch.setattr(settings, "max_messages_per_hour", 2)
    conversation_id = started(client, headers, own_id)
    send(client, headers, conversation_id)
    delete(client, headers, conversation_id)

    response = start(client, headers, own_id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_messages"


def test_deleted_conversations_count_towards_the_conversation_limit(
    client, headers, own_id, monkeypatch
):
    monkeypatch.setattr(settings, "max_conversations_per_day", 2)
    for _ in range(2):
        delete(client, headers, started(client, headers, own_id))

    response = start(client, headers, own_id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_conversations"


def test_resending_a_deleted_conversations_message_starts_a_new_one(client, headers, own_id):
    msg_id = str(uuid.uuid4())
    first = start(client, headers, own_id, msg_id=msg_id).json()["conversation_id"]
    delete(client, headers, first)

    again = start(client, headers, own_id, msg_id=msg_id)

    assert again.status_code == 201
    assert again.json()["conversation_id"] != first


def test_another_accounts_conversation_cannot_be_deleted(
    client, make_user, sign_in, headers, own_id, conversation_id
):
    marias = marias_headers(make_user, sign_in)

    response = delete(client, marias, conversation_id)

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND
    assert listed_ids(client, headers, own_id) == [conversation_id]


def test_unknown_conversation_cannot_be_deleted(client, headers):
    response = delete(client, headers, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND


@pytest.mark.parametrize("stopped_by", [turn_off, remove], ids=["turned-off", "being-deleted"])
def test_conversation_of_a_member_who_cant_be_used_can_still_be_deleted(
    client, headers, azka, stopped_by
):
    """Deleting a conversation doesn't use the profile, so it isn't refused (unlike
    feedback)."""
    conversation_id = started(client, headers, azka, "Azka has stomach aches.")
    stopped_by(client, headers, azka)

    response = delete(client, headers, conversation_id)

    assert response.status_code == 204
    assert client.get(f"/conversations/{conversation_id}", headers=headers).status_code == 404
