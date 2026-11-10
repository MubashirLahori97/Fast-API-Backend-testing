"""Story 3.1: Start or Continue a Conversation."""

import json
import logging
import threading
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.accounts.models import PolicyVersion
from app.conversations import jobs as safety_jobs
from app.conversations import service
from app.conversations.models import Conversation, HealthConsent, Message
from app.conversations.service import (
    SAFETY_CHECK_JOB,
    age_band,
    check_message_safety,
    profile_context,
)
from app.core.audit import AuditEvent
from app.core.config import Settings, settings
from app.core.jobs import Job
from app.main import app
from app.oracle.contract import OracleError, ProfileContext, SafetyCheck, SafetyContext
from app.oracle.dependencies import get_oracle
from app.oracle.fake import FakeOracle
from app.profiles.models import Profile
from app.worker import HANDLERS, load_handlers
from tests.helpers import bearer
from tests.test_intake_family import add_member, error
from tests.test_manage_family import own_profile_id, remove, turn_off
from tests.test_sign_up import VALID

OPENING = "How are you feeling today?"
FIRST_MESSAGE = "Waking at 3am every night."
TOPIC = "waking at 3am every night"  # what the fake Oracle makes of FIRST_MESSAGE
WELCOME_BACK = (
    "Welcome back, Sarah. Last time we talked about waking at 3am every night. "
    "How have things been since then?"
)
CHOICE = {"type": "choice", "options": ["Yes", "No"]}
HEALTH_CONSENT_REQUIRED = "Please accept the Health Consent so I can help you."
ACTION_FAILED = "We couldn’t do that just now. Please try again."
REPLY_FAILED = {"code": "reply_failed", "message": ACTION_FAILED}
TRIAL_ENDED = {
    "code": "trial_ended",
    "message": "Your free trial has ended. Choose a plan to keep talking with me.",
    "field": None,
}
TURNED_OFF = {
    "code": "profile_turned_off",
    "message": "Azka’s profile is turned off.",
    "field": None,
}
BEING_DELETED = {
    "code": "deletion_requested",
    "message": "Azka’s data is being deleted, so their profile can’t be used.",
    "field": None,
}
NOT_SET_UP = {
    "code": "intake_incomplete",
    "message": "Please finish setting up this profile first.",
    "field": None,
}
CONVERSATION_NOT_FOUND = {
    "code": "conversation_not_found",
    "message": "We couldn’t find that conversation.",
    "field": None,
}
NAME_TOO_LONG = "Please keep this to 100 characters or fewer."


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


def start(client, headers, profile_id, text=FIRST_MESSAGE, msg_id=None):
    return client.post(
        f"/profiles/{profile_id}/conversations",
        headers=headers,
        json={"client_msg_id": msg_id or str(uuid.uuid4()), "text": text},
    )


def send(client, headers, conversation_id, text="It started last month.", msg_id=None, **extra):
    return client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers,
        json={"client_msg_id": msg_id or str(uuid.uuid4()), "text": text, **extra},
    )


def reply(client, headers, conversation_id):
    return client.post(f"/conversations/{conversation_id}/reply", headers=headers)


def open_conversation(client, headers, conversation_id) -> dict:
    return client.get(f"/conversations/{conversation_id}", headers=headers).json()


def roles_and_texts(client, headers, conversation_id) -> list[tuple[str, str]]:
    messages = open_conversation(client, headers, conversation_id)["messages"]
    return [(message["role"], message["text"]) for message in messages]


def listed_ids(client, headers, profile_id) -> list[str]:
    rows = client.get(f"/profiles/{profile_id}/conversations", headers=headers).json()
    return [row["id"] for row in rows]


def consent_accepted(client, headers, profile_id) -> bool:
    return client.get(f"/profiles/{profile_id}/health-consent", headers=headers).json()["accepted"]


def accept_consent(client, headers, profile_id):
    policy = client.get(f"/profiles/{profile_id}/health-consent", headers=headers).json()["policy"]
    return client.post(
        f"/profiles/{profile_id}/health-consent",
        headers=headers,
        json={"policy_version_id": policy["id"]},
    )


def started(client, headers, profile_id, text=FIRST_MESSAGE) -> str:
    """Starts a conversation and returns its id."""
    return start(client, headers, profile_id, text).json()["conversation_id"]


def answered(client, headers, profile_id, text=FIRST_MESSAGE) -> str:
    """Accepts the Health Consent, starts a conversation and gets the Oracle's first reply."""
    accept_consent(client, headers, profile_id)
    conversation_id = started(client, headers, profile_id, text)
    reply(client, headers, conversation_id)
    return conversation_id


def sse(response) -> list[tuple[str, dict]]:
    """The server-sent events in a reply, as (event name, data)."""
    found = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        found.append((lines["event"], json.loads(lines["data"])))
    return found


def use(client, headers, action, profile_id, conversation_id=None):
    """Uses a profile: opens the New Conversation screen, starts a conversation, or sends a
    message and asks for the reply in one already started."""
    if action == "new":
        return client.get(f"/profiles/{profile_id}/conversations/new", headers=headers)
    if action == "start":
        return start(client, headers, profile_id)
    if action == "send":
        return send(client, headers, conversation_id)
    return reply(client, headers, conversation_id)


def publish_health_consent(db) -> PolicyVersion:
    policy = PolicyVersion(
        kind="health_consent",
        version="2.0",
        title="Health Consent",
        published_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(policy)
    db.commit()
    return policy


def current_consent_id(db) -> uuid.UUID:
    return db.scalar(select(PolicyVersion.id).where(PolicyVersion.kind == "health_consent"))


def end_trial(db, user) -> None:
    user.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()


def picked_up_after(db, conversation_id, hours) -> None:
    """Moves the conversation's last message `hours` into the past."""
    conversation = db.get(Conversation, uuid.UUID(conversation_id))
    conversation.last_message_at = datetime.now(UTC) - timedelta(hours=hours)
    db.commit()


def client_message(db) -> Message:
    """The only client message in the test, as saved now."""
    return db.scalars(
        select(Message).where(Message.role == "client").execution_options(populate_existing=True)
    ).one()


def audit_events(db, action) -> list[AuditEvent]:
    return db.scalars(select(AuditEvent).where(AuditEvent.action == action)).all()


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


class ChangesMidReply(FakeOracle):
    """A fake Oracle that changes something while it's generating its reply."""

    def __init__(self, change) -> None:
        super().__init__()
        self.change = change

    def stream_reply(self, context, history, earlier):
        self.change()
        yield from super().stream_reply(context, history, earlier)


def use_oracle(oracle) -> None:
    # The client fixture clears the overrides after the test.
    app.dependency_overrides[get_oracle] = lambda: oracle


# The New Conversation screen


def test_new_conversation_screen_for_the_client(client, headers, own_id, oracle):
    response = client.get(f"/profiles/{own_id}/conversations/new", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "opening": OPENING,
        "starters": [
            "Why am I so exhausted all the time?",
            "My labs look normal but I feel terrible",
        ],
    }


def test_new_conversation_screen_for_a_family_member(client, headers, azka):
    response = client.get(f"/profiles/{azka}/conversations/new", headers=headers)

    assert response.json() == {
        "opening": "How is Azka feeling today?",
        "starters": [
            "Why is Azka so exhausted all the time?",
            "Azka’s labs look normal, but something feels off",
        ],
    }


def test_new_conversation_screen_does_not_call_the_oracle(client, headers, own_id, oracle):
    client.get(f"/profiles/{own_id}/conversations/new", headers=headers)

    assert oracle.calls == []


# Starting a conversation


def test_first_message_starts_a_conversation(client, headers, own_id):
    msg_id = str(uuid.uuid4())

    response = start(client, headers, own_id, msg_id=msg_id)

    assert response.status_code == 201
    body = response.json()
    message = body["message"]
    assert message.pop("id") and message.pop("created_at")
    assert message == {
        "role": "client",
        "text": FIRST_MESSAGE,
        "client_msg_id": msg_id,
        "answer": None,
        "widgets": None,
        "feedback": None,  # only the Oracle's replies can be rated
    }
    assert open_conversation(client, headers, body["conversation_id"])["profile_id"] == own_id


def test_opening_question_is_saved_before_the_first_message(client, db, headers, own_id):
    conversation_id = started(client, headers, own_id)

    messages = open_conversation(client, headers, conversation_id)["messages"]

    assert [(m["role"], m["text"]) for m in messages] == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
    ]
    assert (messages[0]["client_msg_id"], messages[0]["widgets"]) == (None, None)
    opening = db.get(Message, uuid.UUID(messages[0]["id"]))
    assert opening.reply_to_id is None


def test_family_members_opening_question_is_saved(client, headers, azka):
    conversation_id = started(client, headers, azka, "Azka has stomach aches.")

    assert roles_and_texts(client, headers, conversation_id)[0] == (
        "oracle",
        "How is Azka feeling today?",
    )


def test_health_consent_comes_after_the_first_message(client, headers, own_id):
    response = start(client, headers, own_id)

    assert response.json()["next"] == "health_consent"


def test_resent_first_message_returns_the_saved_one(client, db, headers, own_id):
    msg_id = str(uuid.uuid4())
    first = start(client, headers, own_id, msg_id=msg_id)

    again = start(client, headers, own_id, msg_id=msg_id)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert (count(db, Conversation), count(db, Message)) == (1, 2)  # the opening and the message


# The Health Consent


def test_health_consent_is_not_accepted_at_first(client, headers, own_id):
    response = client.get(f"/profiles/{own_id}/health-consent", headers=headers)

    assert response.status_code == 200
    body = response.json()
    policy = body["policy"]
    assert body["accepted"] is False
    assert set(policy) == {"id", "kind", "version", "title", "url", "published_at"}
    assert (policy["kind"], policy["version"], policy["title"]) == (
        "health_consent",
        "1.0",
        "Health Consent",
    )


def test_accepting_the_health_consent(client, headers, own_id):
    response = accept_consent(client, headers, own_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["accepted"], body["policy"]["version"]) == (True, "1.0")
    assert consent_accepted(client, headers, own_id) is True


def test_accepting_the_health_consent_is_audited(client, db, user, headers, own_id):
    accept_consent(client, headers, own_id)

    [event] = audit_events(db, "health_consent.accepted")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        user.id,
        "profile",
        own_id,
        {"version": "1.0"},
    )


def test_accepting_twice_records_one_event(client, db, headers, own_id):
    accept_consent(client, headers, own_id)

    again = accept_consent(client, headers, own_id)

    assert again.json()["accepted"] is True
    assert len(audit_events(db, "health_consent.accepted")) == 1


def test_next_is_reply_once_the_health_consent_is_accepted(client, headers, own_id):
    accept_consent(client, headers, own_id)

    response = start(client, headers, own_id)

    assert response.json()["next"] == "reply"


def test_reply_waits_for_the_health_consent(client, headers, own_id):
    conversation_id = started(client, headers, own_id)

    response = reply(client, headers, conversation_id)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "health_consent_required",
        "message": HEALTH_CONSENT_REQUIRED,
        "field": None,
    }


def test_clients_health_consent_does_not_cover_a_family_member(client, headers, own_id, azka):
    accept_consent(client, headers, own_id)

    response = start(client, headers, azka)

    assert consent_accepted(client, headers, azka) is False
    assert response.json()["next"] == "health_consent"


def test_family_members_health_consent_does_not_cover_the_client(client, headers, own_id, azka):
    accept_consent(client, headers, azka)

    response = start(client, headers, own_id)

    assert consent_accepted(client, headers, own_id) is False
    assert response.json()["next"] == "health_consent"


def test_health_consent_needs_a_version(client, headers, own_id):
    response = client.post(f"/profiles/{own_id}/health-consent", headers=headers, json={})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "health_consent_required",
        "message": HEALTH_CONSENT_REQUIRED,
        "field": "policy_version_id",
    }
    assert consent_accepted(client, headers, own_id) is False


def test_unknown_health_consent_version_is_outdated(client, headers, own_id):
    response = client.post(
        f"/profiles/{own_id}/health-consent",
        headers=headers,
        json={"policy_version_id": str(uuid.uuid4())},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "health_consent_outdated",
        "message": HEALTH_CONSENT_REQUIRED,
        "field": "policy_version_id",
    }
    assert consent_accepted(client, headers, own_id) is False


def test_previous_health_consent_version_is_outdated(client, db, headers, own_id):
    old = client.get(f"/profiles/{own_id}/health-consent", headers=headers).json()["policy"]
    publish_health_consent(db)

    response = client.post(
        f"/profiles/{own_id}/health-consent",
        headers=headers,
        json={"policy_version_id": old["id"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "health_consent_outdated"
    assert consent_accepted(client, headers, own_id) is False


def test_new_health_consent_version_needs_accepting_again(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    publish_health_consent(db)

    body = client.get(f"/profiles/{own_id}/health-consent", headers=headers).json()

    assert (body["accepted"], body["policy"]["version"]) == (False, "2.0")


def test_reply_waits_for_the_new_health_consent_version(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    publish_health_consent(db)

    sent = send(client, headers, conversation_id)
    response = reply(client, headers, conversation_id)

    assert sent.json()["next"] == "health_consent"
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "health_consent_required"


def test_consent_accepted_by_another_account_does_not_count(client, db, make_user, headers, own_id):
    maria = make_user(email="maria@example.com")
    db.add(
        HealthConsent(
            profile_id=uuid.UUID(own_id),
            policy_version_id=current_consent_id(db),
            accepted_by_id=maria.id,
        )
    )
    db.commit()

    assert consent_accepted(client, headers, own_id) is False


def test_account_holder_can_accept_after_another_accounts_consent(
    client, db, make_user, headers, own_id
):
    # For example a profile moved to another account (docs/PLAN.md, Phase 10).
    maria = make_user(email="maria@example.com")
    db.add(
        HealthConsent(
            profile_id=uuid.UUID(own_id),
            policy_version_id=current_consent_id(db),
            accepted_by_id=maria.id,
        )
    )
    db.commit()

    response = accept_consent(client, headers, own_id)

    assert response.json()["accepted"] is True


# The Oracle's reply


def test_reply_streams_in_pieces(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    response = reply(client, headers, conversation_id)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    found = sse(response)
    names = [name for name, _ in found]
    assert len(names) > 2
    assert names == ["delta"] * (len(names) - 1) + ["done"]
    assert "".join(data["text"] for _, data in found[:-1]) == oracle.reply


def test_reply_ends_with_the_saved_message(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    name, data = sse(reply(client, headers, conversation_id))[-1]

    message = data["message"]
    assert name == "done"
    assert (
        message["role"],
        message["text"],
        message["client_msg_id"],
        message["answer"],
        message["widgets"],
    ) == ("oracle", oracle.reply, None, None, None)
    # The same id, and times in the same format, as the rest of the API.
    assert open_conversation(client, headers, conversation_id)["messages"][-1] == message
    assert message["created_at"].endswith("Z")


def test_reply_is_saved_in_the_history(client, headers, own_id, oracle):
    conversation_id = answered(client, headers, own_id)

    body = open_conversation(client, headers, conversation_id)

    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
        ("oracle", oracle.reply),
    ]
    assert body["awaiting_reply"] is False


def test_topic_is_empty_before_the_first_reply(client, headers, own_id):
    conversation_id = started(client, headers, own_id)

    body = open_conversation(client, headers, conversation_id)

    assert (body["topic"], body["welcome_back"], body["awaiting_reply"]) == (None, None, True)


def test_first_reply_sets_the_topic(client, headers, own_id):
    conversation_id = answered(client, headers, own_id)

    assert open_conversation(client, headers, conversation_id)["topic"] == TOPIC


def test_topic_is_cleaned(client, headers, own_id, oracle, monkeypatch):
    monkeypatch.setattr(oracle, "topic", lambda context, history: " waking​  at \n 3am‮ ")

    conversation_id = answered(client, headers, own_id)

    assert open_conversation(client, headers, conversation_id)["topic"] == "waking at 3am"


def test_topic_is_cut_to_100_characters(client, headers, own_id, oracle, monkeypatch):
    monkeypatch.setattr(oracle, "topic", lambda context, history: "x" * 150)

    conversation_id = answered(client, headers, own_id)

    assert open_conversation(client, headers, conversation_id)["topic"] == "x" * 100


def test_saved_reply_is_sent_again_whole(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    first = sse(reply(client, headers, conversation_id))

    again = sse(reply(client, headers, conversation_id))

    assert again == [("delta", {"text": oracle.reply}), first[-1]]
    assert oracle.calls.count("stream_reply") == 1


def test_reply_that_fails_part_way_sends_an_error(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    oracle.fail_after = 2

    found = sse(reply(client, headers, conversation_id))

    assert [name for name, _ in found] == ["delta", "delta", "error"]
    assert found[-1][1] == REPLY_FAILED


def test_failed_reply_saves_nothing(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    oracle.fail_after = 2

    reply(client, headers, conversation_id)

    body = open_conversation(client, headers, conversation_id)
    assert [m["role"] for m in body["messages"]] == ["oracle", "client"]
    assert (body["topic"], body["awaiting_reply"]) == (None, True)


def test_retry_after_a_failed_reply_saves_it(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    oracle.fail_after = 2
    reply(client, headers, conversation_id)
    oracle.fail_after = None

    found = sse(reply(client, headers, conversation_id))

    assert found[-1][0] == "done"
    body = open_conversation(client, headers, conversation_id)
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
        ("oracle", oracle.reply),
    ]
    assert body["awaiting_reply"] is False


def test_reply_answers_the_latest_client_message(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    second = send(client, headers, conversation_id, "And I'm tired all day.").json()["message"]

    reply(client, headers, conversation_id)

    oracle_reply = db.scalars(select(Message).where(Message.reply_to_id.is_not(None))).one()
    assert oracle_reply.reply_to_id == uuid.UUID(second["id"])


# Widgets and tapped answers


def test_widgets_are_sent_after_the_text(client, headers, own_id, oracle):
    oracle.widgets = [CHOICE]
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    found = sse(reply(client, headers, conversation_id))

    assert [name for name, _ in found[-3:]] == ["delta", "widget", "done"]
    assert found[-2][1] == {"widget": CHOICE}
    assert found[-1][1]["message"]["widgets"] == [CHOICE]


def test_widgets_are_saved_with_the_reply(client, headers, own_id, oracle):
    oracle.widgets = [CHOICE]

    conversation_id = answered(client, headers, own_id)

    assert open_conversation(client, headers, conversation_id)["messages"][-1]["widgets"] == [
        CHOICE
    ]


def test_replay_sends_the_widgets_too(client, headers, own_id, oracle):
    oracle.widgets = [CHOICE]
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    first = sse(reply(client, headers, conversation_id))

    again = sse(reply(client, headers, conversation_id))

    assert again == [("delta", {"text": oracle.reply}), ("widget", {"widget": CHOICE}), first[-1]]


def test_tapped_answer_is_saved_with_the_message(client, headers, own_id):
    conversation_id = answered(client, headers, own_id)

    response = send(client, headers, conversation_id, "Yes", answer={"value": "yes"})

    assert response.json()["message"]["answer"] == {"value": "yes"}
    assert open_conversation(client, headers, conversation_id)["messages"][-1]["answer"] == {
        "value": "yes"
    }


def test_answer_over_2000_characters_is_refused(client, headers, own_id):
    conversation_id = started(client, headers, own_id)

    response = send(client, headers, conversation_id, "Yes", answer={"value": "x" * 2000})

    assert response.status_code == 422
    assert error(response) == ("answer", "That answer is too long to save.")


# What the Oracle is given with a reply


def test_oracle_is_given_the_conversation_so_far(client, headers, own_id, oracle):
    first_reply = oracle.reply
    conversation_id = answered(client, headers, own_id)
    send(client, headers, conversation_id, "It started last month.")

    reply(client, headers, conversation_id)

    assert [(turn.role, turn.text) for turn in oracle.last_history] == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
        ("oracle", first_reply),
        ("client", "It started last month."),
    ]


def test_oracle_history_is_cut_to_the_latest_messages(client, headers, own_id, oracle, monkeypatch):
    monkeypatch.setattr(settings, "oracle_history_messages", 2)
    first_reply = oracle.reply
    conversation_id = answered(client, headers, own_id)
    send(client, headers, conversation_id, "It started last month.")

    reply(client, headers, conversation_id)

    assert [(turn.role, turn.text) for turn in oracle.last_history] == [
        ("oracle", first_reply),
        ("client", "It started last month."),
    ]


def test_oracle_sees_its_widgets_and_the_tapped_answer(client, headers, own_id, oracle):
    oracle.widgets = [CHOICE]
    conversation_id = answered(client, headers, own_id)
    send(client, headers, conversation_id, "Yes", answer={"value": "yes"})

    reply(client, headers, conversation_id)

    earlier_reply, answer = oracle.last_history[-2:]
    assert earlier_reply.widgets == [CHOICE]
    assert (answer.text, answer.answer) == ("Yes", {"value": "yes"})


def test_oracle_is_given_the_profiles_earlier_conversations(client, headers, own_id, oracle):
    first_reply = oracle.reply
    answered(client, headers, own_id)
    second = started(client, headers, own_id, "My knees ache in the morning.")

    reply(client, headers, second)

    [earlier] = oracle.last_earlier
    assert earlier.topic == TOPIC
    assert [(turn.role, turn.text) for turn in earlier.turns] == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
        ("oracle", first_reply),
    ]


def test_earlier_conversations_are_the_latest_newest_first(
    client, headers, own_id, oracle, monkeypatch
):
    monkeypatch.setattr(settings, "oracle_earlier_conversations", 2)
    monkeypatch.setattr(settings, "oracle_earlier_messages", 1)
    for text in ("First concern.", "Second concern.", "Third concern."):
        started(client, headers, own_id, text)
    accept_consent(client, headers, own_id)
    latest = started(client, headers, own_id, "Fourth concern.")

    reply(client, headers, latest)

    assert [[turn.text for turn in earlier.turns] for earlier in oracle.last_earlier] == [
        ["Third concern."],
        ["Second concern."],
    ]


def test_family_members_earlier_conversations_leave_out_the_clients(
    client, headers, own_id, azka, oracle
):
    answered(client, headers, own_id)

    answered(client, headers, azka, "Azka has stomach aches.")

    assert oracle.last_earlier == []


# Continuing a conversation


def test_continuing_a_conversation_adds_the_message(client, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    msg_id = str(uuid.uuid4())

    response = send(client, headers, conversation_id, "It started last month.", msg_id)

    assert response.status_code == 201
    body = response.json()
    message = body["message"]
    assert body["conversation_id"] == conversation_id
    assert (message["role"], message["text"], message["client_msg_id"]) == (
        "client",
        "It started last month.",
        msg_id,
    )
    assert body["next"] == "reply"


def test_resent_message_returns_the_saved_one(client, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    msg_id = str(uuid.uuid4())
    first = send(client, headers, conversation_id, msg_id=msg_id)

    again = send(client, headers, conversation_id, msg_id=msg_id)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert len(open_conversation(client, headers, conversation_id)["messages"]) == 4


def test_new_message_awaits_a_reply(client, headers, own_id):
    conversation_id = answered(client, headers, own_id)

    send(client, headers, conversation_id)

    assert open_conversation(client, headers, conversation_id)["awaiting_reply"] is True


def test_full_history_is_shown_oldest_first(client, headers, own_id, oracle):
    first_reply = oracle.reply
    conversation_id = answered(client, headers, own_id)
    send(client, headers, conversation_id, "It started last month.")
    oracle.reply = "Has anything changed since then?"
    reply(client, headers, conversation_id)

    assert roles_and_texts(client, headers, conversation_id) == [
        ("oracle", OPENING),
        ("client", FIRST_MESSAGE),
        ("oracle", first_reply),
        ("client", "It started last month."),
        ("oracle", "Has anything changed since then?"),
    ]


def test_returning_client_is_welcomed_back(client, db, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    picked_up_after(db, conversation_id, hours=settings.welcome_back_after_hours + 1)

    body = open_conversation(client, headers, conversation_id)

    assert body["welcome_back"] == WELCOME_BACK


def test_no_welcome_back_within_a_few_hours(client, db, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    picked_up_after(db, conversation_id, hours=settings.welcome_back_after_hours - 1)

    body = open_conversation(client, headers, conversation_id)

    assert body["welcome_back"] is None


def test_welcome_back_is_saved_before_the_next_message(client, db, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    picked_up_after(db, conversation_id, hours=settings.welcome_back_after_hours + 1)

    send(client, headers, conversation_id, "Still waking up.")

    assert roles_and_texts(client, headers, conversation_id)[-2:] == [
        ("oracle", WELCOME_BACK),
        ("client", "Still waking up."),
    ]
    assert open_conversation(client, headers, conversation_id)["welcome_back"] is None


# The conversation list


def test_list_shows_the_most_recent_activity_first(client, headers, own_id):
    first = started(client, headers, own_id)
    second = started(client, headers, own_id, "My knees ache in the morning.")
    send(client, headers, first)

    rows = client.get(f"/profiles/{own_id}/conversations", headers=headers).json()

    assert [row["id"] for row in rows] == [first, second]
    assert set(rows[0]) == {"id", "topic", "created_at", "last_message_at"}


def test_list_shows_the_topic(client, headers, own_id):
    answered(client, headers, own_id)

    rows = client.get(f"/profiles/{own_id}/conversations", headers=headers).json()

    assert [row["topic"] for row in rows] == [TOPIC]


def test_each_profile_has_its_own_list(client, headers, own_id, azka):
    sarahs = started(client, headers, own_id)
    azkas = started(client, headers, azka, "Azka has stomach aches after school.")

    assert listed_ids(client, headers, own_id) == [sarahs]
    assert listed_ids(client, headers, azka) == [azkas]


# The safety check (acting on it is story 3.2)


def test_safety_check_runs_on_the_first_message_before_the_health_consent(
    client, db, headers, own_id, oracle
):
    body = start(client, headers, own_id).json()

    assert body["next"] == "health_consent"
    assert oracle.calls == ["check_safety"]
    assert db.get(Message, uuid.UUID(body["message"]["id"])).safety_level == "none"


def test_urgent_safety_result_is_saved_with_the_message(client, db, headers, own_id, oracle):
    oracle.safety = SafetyCheck(level="urgent")

    body = start(client, headers, own_id).json()

    assert db.get(Message, uuid.UUID(body["message"]["id"])).safety_level == "urgent"


def test_safety_check_runs_on_every_message(client, headers, own_id, oracle):
    conversation_id = started(client, headers, own_id)

    send(client, headers, conversation_id)

    assert oracle.calls.count("check_safety") == 2


def test_safety_check_is_given_only_is_self_and_the_age_band(client, headers, azka, oracle):
    started(client, headers, azka, "Azka has stomach aches.")

    assert oracle.last_safety_context == SafetyContext(is_self=False, age_band="under_13")
    assert {field.name for field in fields(SafetyContext)} == {"is_self", "age_band"}


def test_message_is_saved_when_the_safety_check_fails(client, db, headers, own_id, oracle):
    oracle.fail_safety = True

    response = start(client, headers, own_id)

    assert response.status_code == 201
    assert client_message(db).safety_level is None


def test_unknown_safety_level_is_not_saved(client, db, headers, own_id, oracle):
    oracle.safety = SafetyCheck(level="severe")

    response = start(client, headers, own_id)

    assert response.status_code == 201
    assert client_message(db).safety_level is None


def test_reply_runs_a_failed_safety_check_again(client, db, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    oracle.fail_safety = True
    conversation_id = started(client, headers, own_id)
    oracle.fail_safety = False

    found = sse(reply(client, headers, conversation_id))

    assert found[-1][0] == "done"
    assert oracle.calls.count("check_safety") == 2
    assert client_message(db).safety_level == "none"


def test_no_reply_while_the_safety_check_keeps_failing(client, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    oracle.fail_safety = True
    conversation_id = started(client, headers, own_id)

    response = reply(client, headers, conversation_id)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "safety_check_failed",
        "message": ACTION_FAILED,
        "field": None,
    }
    assert "stream_reply" not in oracle.calls


# One reply at a time, and only so many tries


def test_reply_already_in_progress_is_refused(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    client_message(db).reply_started_at = datetime.now(UTC)
    db.commit()

    response = reply(client, headers, conversation_id)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "reply_in_progress",
        "message": "I’m still replying to that message. Please wait a moment.",
        "field": None,
    }


def test_abandoned_reply_can_be_taken_over(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    client_message(db).reply_started_at = datetime.now(UTC) - timedelta(
        seconds=settings.reply_claim_seconds + 1
    )
    db.commit()

    found = sse(reply(client, headers, conversation_id))

    assert found[-1][0] == "done"


def test_failed_reply_frees_the_message_for_a_retry(client, db, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    oracle.fail_after = 2

    reply(client, headers, conversation_id)

    message = client_message(db)
    assert (message.reply_started_at, message.reply_attempts) == (None, 1)


def test_reply_gives_up_after_too_many_attempts(client, db, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    client_message(db).reply_attempts = settings.reply_max_attempts
    db.commit()

    response = reply(client, headers, conversation_id)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_attempts",
        "message": "I couldn’t reply to that message. Please try sending it again.",
        "field": None,
    }
    assert "stream_reply" not in oracle.calls


def test_saved_reply_is_replayed_without_a_claim(client, db, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    client_message(db).reply_started_at = datetime.now(UTC)
    db.commit()

    response = reply(client, headers, conversation_id)

    assert response.status_code == 200
    assert sse(response)[-1][0] == "done"


# How much a client can send


def test_too_many_messages_in_an_hour_are_refused(client, headers, own_id, monkeypatch):
    monkeypatch.setattr(settings, "max_messages_per_hour", 2)
    conversation_id = started(client, headers, own_id)
    send(client, headers, conversation_id)

    response = send(client, headers, conversation_id)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_messages",
        "message": (
            "You’re sending messages faster than I can keep up with. "
            "Please wait a few minutes and try again."
        ),
        "field": None,
    }


def test_message_limit_counts_every_profile_on_the_account(
    client, headers, own_id, azka, monkeypatch
):
    monkeypatch.setattr(settings, "max_messages_per_hour", 2)
    started(client, headers, own_id)
    started(client, headers, azka, "Azka has stomach aches.")

    response = start(client, headers, own_id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_messages"


def test_too_many_conversations_in_a_day_are_refused(client, headers, own_id, monkeypatch):
    monkeypatch.setattr(settings, "max_conversations_per_day", 2)
    started(client, headers, own_id)
    started(client, headers, own_id)

    response = start(client, headers, own_id)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_conversations",
        "message": (
            "You’ve started a lot of conversations today. "
            "Please carry on in one of them, or try again tomorrow."
        ),
        "field": None,
    }


def test_resend_is_answered_after_the_message_limit(client, headers, own_id, monkeypatch):
    monkeypatch.setattr(settings, "max_messages_per_hour", 1)
    msg_id = str(uuid.uuid4())
    first = start(client, headers, own_id, msg_id=msg_id)

    again = start(client, headers, own_id, msg_id=msg_id)

    assert again.status_code == 200
    assert again.json() == first.json()


# The free trial


def on_trial(client, make_user, sign_in):
    """Sarah on the free trial, with the Health Consent accepted and a conversation started.
    Returns (user, headers, profile id, conversation id)."""
    user = make_user()
    headers = bearer(sign_in()["access_token"])
    profile_id = own_profile_id(client, headers)
    accept_consent(client, headers, profile_id)
    return user, headers, profile_id, started(client, headers, profile_id)


@pytest.mark.parametrize("action", ["start", "send", "reply"])
def test_trial_ended_client_cannot_talk(client, db, make_user, sign_in, action):
    user, headers, profile_id, conversation_id = on_trial(client, make_user, sign_in)
    end_trial(db, user)

    response = use(client, headers, action, profile_id, conversation_id)

    assert response.status_code == 403
    assert response.json()["error"] == TRIAL_ENDED


def test_trial_ended_client_can_still_read_conversations(client, db, make_user, sign_in):
    user, headers, profile_id, conversation_id = on_trial(client, make_user, sign_in)
    end_trial(db, user)

    opened = client.get(f"/conversations/{conversation_id}", headers=headers)

    assert opened.status_code == 200
    assert [m["text"] for m in opened.json()["messages"]] == [OPENING, FIRST_MESSAGE]
    assert listed_ids(client, headers, profile_id) == [conversation_id]


def test_resend_is_answered_after_the_trial_ended(client, db, make_user, sign_in):
    user = make_user()
    headers = bearer(sign_in()["access_token"])
    profile_id = own_profile_id(client, headers)
    msg_id = str(uuid.uuid4())
    first = start(client, headers, profile_id, msg_id=msg_id)
    end_trial(db, user)

    again = start(client, headers, profile_id, msg_id=msg_id)

    assert again.status_code == 200
    assert again.json() == first.json()


def test_subscribed_client_can_talk_after_the_trial_date(client, db, user, headers, own_id):
    end_trial(db, user)  # Sarah is on the Basic plan
    accept_consent(client, headers, own_id)

    response = start(client, headers, own_id)
    found = sse(reply(client, headers, response.json()["conversation_id"]))

    assert response.status_code == 201
    assert found[-1][0] == "done"


def test_entitlements_say_when_the_trial_has_ended(client, db, make_user, sign_in):
    user = make_user()
    headers = bearer(sign_in()["access_token"])
    during = client.get("/me/entitlements", headers=headers).json()
    end_trial(db, user)

    after = client.get("/me/entitlements", headers=headers).json()

    assert (during["trial_ended"], after["trial_ended"]) == (False, True)


def test_subscribed_clients_trial_never_ends(client, db, user, headers):
    end_trial(db, user)  # Sarah is on the Basic plan

    body = client.get("/me/entitlements", headers=headers).json()

    assert body["trial_ended"] is False


# Profiles that can't be used


@pytest.mark.parametrize("action", ["new", "start", "send", "reply"])
def test_turned_off_member_cannot_be_talked_about(client, headers, azka, action):
    accept_consent(client, headers, azka)
    conversation_id = started(client, headers, azka)  # before she was turned off
    turn_off(client, headers, azka)

    response = use(client, headers, action, azka, conversation_id)

    assert response.status_code == 409
    assert response.json()["error"] == TURNED_OFF


def test_turned_off_members_conversations_can_still_be_read(client, headers, azka):
    conversation_id = answered(client, headers, azka)
    turn_off(client, headers, azka)

    opened = client.get(f"/conversations/{conversation_id}", headers=headers)

    assert opened.status_code == 200
    assert len(opened.json()["messages"]) == 3
    assert listed_ids(client, headers, azka) == [conversation_id]


@pytest.mark.parametrize("action", ["new", "start", "send", "reply"])
def test_member_being_deleted_cannot_be_talked_about(client, headers, azka, action):
    accept_consent(client, headers, azka)
    conversation_id = started(client, headers, azka)
    remove(client, headers, azka)

    response = use(client, headers, action, azka, conversation_id)

    assert response.status_code == 409
    assert response.json()["error"] == BEING_DELETED


@pytest.mark.parametrize("action", ["new", "start"])
def test_unfinished_profile_cannot_be_talked_about(client, make_user, sign_in, action):
    make_user(intake_done=False)
    headers = bearer(sign_in()["access_token"])
    profile_id = client.post("/profiles/self", headers=headers).json()["profile_id"]

    response = use(client, headers, action, profile_id)

    assert response.status_code == 409
    assert response.json()["error"] == NOT_SET_UP


def test_member_turned_off_while_the_reply_streams(client, db, headers, azka):
    accept_consent(client, headers, azka)
    conversation_id = started(client, headers, azka)

    def turn_off_azka():
        db.get(Profile, uuid.UUID(azka)).turned_off_at = datetime.now(UTC)
        db.commit()

    use_oracle(ChangesMidReply(turn_off_azka))

    found = sse(reply(client, headers, conversation_id))

    assert found[-1] == ("error", {"code": TURNED_OFF["code"], "message": TURNED_OFF["message"]})
    assert [role for role, _ in roles_and_texts(client, headers, conversation_id)] == [
        "oracle",
        "client",
    ]


def test_health_consent_outdated_while_the_reply_streams(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    use_oracle(ChangesMidReply(lambda: publish_health_consent(db)))

    found = sse(reply(client, headers, conversation_id))

    assert found[-1] == (
        "error",
        {"code": "health_consent_required", "message": HEALTH_CONSENT_REQUIRED},
    )
    assert [role for role, _ in roles_and_texts(client, headers, conversation_id)] == [
        "oracle",
        "client",
    ]


# Another client's profiles and conversations


def marias_headers(make_user, sign_in) -> dict[str, str]:
    make_user(email="maria@example.com")
    return bearer(sign_in(email="maria@example.com")["access_token"])


def valid_body(db, path) -> dict | None:
    if path.endswith(("/conversations", "/messages")):
        return {"client_msg_id": str(uuid.uuid4()), "text": FIRST_MESSAGE}
    if path.endswith("/health-consent"):
        return {"policy_version_id": str(current_consent_id(db))}
    return None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/profiles/{id}/conversations"),
        ("get", "/profiles/{id}/conversations/new"),
        ("post", "/profiles/{id}/conversations"),
        ("get", "/profiles/{id}/health-consent"),
        ("post", "/profiles/{id}/health-consent"),
    ],
)
def test_another_clients_profile_is_not_found(client, db, make_user, sign_in, own_id, method, path):
    headers = marias_headers(make_user, sign_in)
    body = valid_body(db, path) if method == "post" else None

    response = client.request(method, path.format(id=own_id), headers=headers, json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/conversations/{id}"),
        ("post", "/conversations/{id}/messages"),
        ("post", "/conversations/{id}/reply"),
    ],
)
def test_another_clients_conversation_is_not_found(
    client, db, make_user, sign_in, headers, own_id, method, path
):
    conversation_id = answered(client, headers, own_id)
    marias = marias_headers(make_user, sign_in)
    body = valid_body(db, path) if method == "post" else None

    response = client.request(method, path.format(id=conversation_id), headers=marias, json=body)

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND


def test_unknown_conversation_is_not_found(client, headers):
    response = client.get(f"/conversations/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"] == CONVERSATION_NOT_FOUND


# Validation


@pytest.mark.parametrize(
    "text_field", [{"text": ""}, {"text": "  \n\t "}, {}], ids=["empty", "whitespace", "missing"]
)
def test_empty_message_is_refused(client, headers, own_id, text_field):
    response = client.post(
        f"/profiles/{own_id}/conversations",
        headers=headers,
        json={"client_msg_id": str(uuid.uuid4()), **text_field},
    )

    assert response.status_code == 422
    assert error(response) == ("text", "Please type a message to send.")


def test_empty_message_in_a_conversation_is_refused(client, headers, own_id):
    conversation_id = started(client, headers, own_id)

    response = send(client, headers, conversation_id, "   ")

    assert response.status_code == 422
    assert error(response) == ("text", "Please type a message to send.")


def test_message_over_8000_characters_is_refused(client, headers, own_id):
    response = start(client, headers, own_id, "x" * 8001)

    assert response.status_code == 422
    assert error(response) == (
        "text",
        "That message is too long. Please keep it to 8,000 characters or fewer.",
    )


def test_message_of_8000_characters_is_accepted(client, headers, own_id):
    response = start(client, headers, own_id, "x" * 8000)

    assert response.status_code == 201


def test_long_narrative_is_accepted(client, headers, own_id):
    # Longer than the 1,000 characters allowed in other request fields.
    response = start(client, headers, own_id, "x" * 5000)

    assert response.status_code == 201
    assert len(response.json()["message"]["text"]) == 5000


def test_message_text_is_trimmed(client, headers, own_id):
    response = start(client, headers, own_id, f"  {FIRST_MESSAGE}\n")

    assert response.json()["message"]["text"] == FIRST_MESSAGE


def test_control_characters_are_removed_from_a_message(client, headers, own_id):
    response = start(client, headers, own_id, "Waking\x00 at 3am\x07 every night.")

    assert response.status_code == 201
    assert response.json()["message"]["text"] == FIRST_MESSAGE


def test_line_breaks_and_tabs_are_kept_in_a_message(client, headers, own_id):
    response = start(client, headers, own_id, "Line one\r\nLine two\twith a tab")

    assert response.json()["message"]["text"] == "Line one\nLine two\twith a tab"


def test_message_needs_its_client_msg_id(client, headers, own_id):
    response = client.post(
        f"/profiles/{own_id}/conversations", headers=headers, json={"text": FIRST_MESSAGE}
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "client_msg_id"


# What the Oracle is told about the profile


def test_profile_context_for_a_family_member(db, user, azka):
    context = profile_context(db.get(Profile, uuid.UUID(azka)), user)

    assert (
        context.is_self,
        context.first_name,
        context.advocate_first_name,
        context.relationship,
        context.age_band,
    ) == (False, "Azka", "Sarah", "child", "under_13")


def test_profile_context_for_the_client(db, user, own_id):
    context = profile_context(db.get(Profile, uuid.UUID(own_id)), user)

    assert (
        context.is_self,
        context.first_name,
        context.relationship,
        context.age_band,
        context.sex_at_birth,
        context.pronouns,
    ) == (True, "Sarah", None, "18_59", "female", "she_her")


def test_profile_context_leaves_out_the_date_of_birth_and_advocate_consent():
    names = {field.name for field in fields(ProfileContext)}

    assert "date_of_birth" not in names
    assert "advocate_consent" not in names


@pytest.mark.parametrize(
    ("born", "band"),
    [
        (date(2013, 10, 31), "under_13"),  # turns 13 tomorrow
        (date(2013, 10, 30), "13_17"),
        (date(2008, 10, 31), "13_17"),
        (date(2008, 10, 30), "18_59"),
        (date(1966, 10, 31), "18_59"),
        (date(1966, 10, 30), "60_plus"),
    ],
    ids=["12", "13", "17", "18", "59", "60"],
)
def test_age_band_boundaries(born, band):
    assert age_band(born, date(2026, 10, 30)) == band


@pytest.mark.parametrize(
    ("today", "band"), [(date(2026, 2, 28), "13_17"), (date(2026, 3, 1), "18_59")]
)
def test_age_band_for_a_leap_day_birthday(today, band):
    assert age_band(date(2008, 2, 29), today) == band


# Names, which reach the Oracle's prompts


def family_first_name(client, headers, first_name):
    profile_id = client.post("/profiles/family", headers=headers).json()["profile_id"]
    return client.patch(
        f"/profiles/{profile_id}/intake", headers=headers, json={"first_name": first_name}
    )


def test_sign_up_first_name_over_100_characters_is_refused(client):
    response = client.post("/auth/signup", json={**VALID, "first_name": "S" * 101})

    assert response.status_code == 422
    assert error(response) == ("first_name", NAME_TOO_LONG)


def test_sign_up_first_name_of_only_hidden_characters_is_empty(client):
    response = client.post("/auth/signup", json={**VALID, "first_name": "​"})

    assert response.status_code == 422
    assert error(response) == ("first_name", "Please enter your first name.")


@pytest.mark.parametrize(
    "written",
    ["Az\nka", "Az​ka", "‮Azka", "Ａｚｋａ"],
    ids=["line-break", "zero-width", "bidi", "full-width"],
)
def test_hidden_characters_are_removed_from_a_first_name(client, headers, written):
    response = family_first_name(client, headers, written)

    assert response.json()["first_name"] == "Azka"


def test_spaces_in_a_first_name_are_collapsed(client, headers):
    response = family_first_name(client, headers, "Mary   Ann")

    assert response.json()["first_name"] == "Mary Ann"


@pytest.mark.parametrize("written", ["​", "123", "--"], ids=["zero-width", "digits", "dashes"])
def test_first_name_without_a_letter_is_empty(client, headers, written):
    response = family_first_name(client, headers, written)

    assert response.status_code == 422
    assert error(response) == (
        "first_name",
        "What should I call them? Please enter their first name.",
    )


def test_write_in_over_100_characters_is_refused(client, headers):
    profile_id = client.post("/profiles/family", headers=headers).json()["profile_id"]

    response = client.patch(
        f"/profiles/{profile_id}/intake",
        headers=headers,
        json={"pronouns": "other", "pronouns_other": "x" * 101},
    )

    assert response.status_code == 422
    assert error(response) == ("pronouns_other", NAME_TOO_LONG)


# Record keeping


def test_starting_a_conversation_is_audited(client, db, user, headers, own_id):
    conversation_id = started(client, headers, own_id)

    [event] = audit_events(db, "conversation.started")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        user.id,
        "conversation",
        conversation_id,
        {"profile_id": own_id},
    )


def test_audit_events_hold_no_message_text(client, db, headers, own_id, oracle):
    conversation_id = answered(client, headers, own_id, "Night sweats since my divorce.")
    send(client, headers, conversation_id, "Mostly after midnight.")
    reply(client, headers, conversation_id)

    flattened = str([event.details for event in db.scalars(select(AuditEvent))])

    for secret in ("Night sweats", "night sweats", "divorce", "midnight", oracle.reply):
        assert secret not in flattened


def test_oracle_failures_are_logged_without_the_message(client, headers, own_id, oracle, caplog):
    caplog.set_level(logging.WARNING)
    accept_consent(client, headers, own_id)
    oracle.fail_safety = True
    conversation_id = started(client, headers, own_id, "Night sweats since my divorce.")
    oracle.fail_safety = False
    oracle.fail_after = 2

    reply(client, headers, conversation_id)

    logged = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("Safety check failed: OracleError") for line in logged)
    assert any(line.startswith("Oracle reply failed: OracleError") for line in logged)
    for secret in ("Night sweats", "divorce", "as asked"):  # "as asked": the error's own text
        assert secret not in caplog.text


def test_database_refuses_a_client_message_without_its_id(client, db, headers, own_id):
    conversation_id = started(client, headers, own_id)
    db.add(
        Message(
            conversation_id=uuid.UUID(conversation_id),
            role="client",
            text="Hello",
            safety_level="none",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_database_refuses_a_second_reply_to_the_same_message(client, db, headers, own_id):
    conversation_id = answered(client, headers, own_id)
    question = open_conversation(client, headers, conversation_id)["messages"][1]
    db.add(
        Message(
            conversation_id=uuid.UUID(conversation_id),
            role="oracle",
            text="Another answer",
            reply_to_id=uuid.UUID(question["id"]),
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


# Settings


def test_fake_oracle_is_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(RuntimeError):
        get_oracle()


def test_unknown_environment_is_refused():
    with pytest.raises(ValidationError):
        Settings(environment="prod", database_url="postgresql://x")


# Safety checks that failed when their message was sent (story 3.2)


def messages_by_text(db) -> dict[str, Message]:
    rows = db.scalars(
        select(Message).where(Message.role == "client").execution_options(populate_existing=True)
    )
    return {message.text: message for message in rows}


def test_an_earlier_unchecked_message_blocks_the_reply(client, db, headers, own_id, oracle):
    accept_consent(client, headers, own_id)
    oracle.fail_safety = True
    conversation_id = started(client, headers, own_id, "I can’t see a way forward.")
    oracle.fail_safety = False
    send(client, headers, conversation_id, "hello?")
    oracle.fail_safety = True

    response = reply(client, headers, conversation_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "safety_check_failed"
    assert "stream_reply" not in oracle.calls


def test_an_earlier_unchecked_message_is_checked_before_the_reply(
    client, db, headers, own_id, oracle
):
    accept_consent(client, headers, own_id)
    oracle.fail_safety = True
    conversation_id = started(client, headers, own_id, "I can’t see a way forward.")
    oracle.fail_safety = False
    send(client, headers, conversation_id, "hello?")

    response = reply(client, headers, conversation_id)

    assert sse(response)[-1][0] == "done"
    assert messages_by_text(db)["I can’t see a way forward."].safety_level == "none"


def test_every_message_gets_a_safety_check_job(client, db, headers, own_id):
    conversation_id = started(client, headers, own_id)
    send(client, headers, conversation_id)

    found = db.scalars(select(Job).where(Job.kind == SAFETY_CHECK_JOB)).all()

    message_ids = {str(message.id) for message in messages_by_text(db).values()}
    assert {job.payload["message_id"] for job in found} == message_ids
    assert all(job.run_at > datetime.now(UTC) + timedelta(seconds=30) for job in found)


def test_the_job_checks_a_message_the_send_couldnt(
    client, db, headers, own_id, oracle, monkeypatch
):
    oracle.fail_safety = True
    started(client, headers, own_id)
    oracle.fail_safety = False
    monkeypatch.setattr(safety_jobs, "get_oracle", lambda: oracle)
    message = client_message(db)

    safety_jobs.retry_safety_check(db, {"message_id": str(message.id)})

    assert client_message(db).safety_level == "none"


def test_the_job_fails_while_the_check_keeps_failing(
    client, db, headers, own_id, oracle, monkeypatch
):
    oracle.fail_safety = True
    started(client, headers, own_id)
    monkeypatch.setattr(safety_jobs, "get_oracle", lambda: oracle)

    with pytest.raises(OracleError):
        safety_jobs.retry_safety_check(db, {"message_id": str(client_message(db).id)})
    assert client_message(db).safety_level is None


def test_the_job_does_nothing_once_the_message_is_checked(
    client, db, headers, own_id, oracle, monkeypatch
):
    started(client, headers, own_id)
    monkeypatch.setattr(safety_jobs, "get_oracle", lambda: oracle)
    oracle.calls.clear()

    safety_jobs.retry_safety_check(db, {"message_id": str(client_message(db).id)})

    assert oracle.calls == []


def test_the_worker_knows_the_safety_check_job():
    load_handlers()

    assert SAFETY_CHECK_JOB in HANDLERS


def test_a_stored_safety_level_is_never_overwritten(client, db, headers, own_id, oracle):
    started(client, headers, own_id)
    message = client_message(db)
    message.safety_level = "crisis"
    db.commit()
    profile = db.get(Profile, uuid.UUID(own_id))

    level = check_message_safety(db, message, profile, oracle)

    assert level == "crisis"
    assert client_message(db).safety_level == "crisis"


# Reply claims after the second review


def test_a_busy_server_doesnt_use_up_an_attempt(client, db, headers, own_id, monkeypatch):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)
    monkeypatch.setattr(service, "_reply_streams", threading.BoundedSemaphore(1))
    service._reply_streams.acquire()  # every stream slot is taken

    events = sse(reply(client, headers, conversation_id))

    assert events == [("error", {"code": "busy", "message": ACTION_FAILED})]
    message = client_message(db)
    assert (message.reply_attempts, message.reply_started_at) == (0, None)


def test_an_oracle_that_fails_straight_away_releases_the_claim(client, db, headers, own_id):
    class FailsAtOnce(FakeOracle):
        def stream_reply(self, context, history, earlier):
            raise OracleError("The fake Oracle failed before streaming, as asked.")

    use_oracle(FailsAtOnce())
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    events = sse(reply(client, headers, conversation_id))

    assert events == [("error", REPLY_FAILED)]
    message = client_message(db)
    assert (message.reply_attempts, message.reply_started_at) == (1, None)


def test_a_stream_only_releases_its_own_claim(client, db, headers, own_id):
    started(client, headers, own_id)
    message = client_message(db)
    taken_over_at = datetime.now(UTC)
    message.reply_started_at = taken_over_at
    db.commit()
    stale = service.ReplyClaim(message, taken_over_at - timedelta(minutes=3))

    service._release_claim(db, stale)

    assert client_message(db).reply_started_at == taken_over_at


def test_resending_a_message_with_no_attempts_left_says_send_again(client, db, headers, own_id):
    accept_consent(client, headers, own_id)
    msg_id = str(uuid.uuid4())
    start(client, headers, own_id, msg_id=msg_id)
    message = client_message(db)
    message.reply_attempts = settings.reply_max_attempts
    db.commit()

    response = start(client, headers, own_id, msg_id=msg_id)

    assert response.status_code == 200
    assert response.json()["next"] == "send_again"


# Input cleaning and headers after the second review


def test_hidden_characters_are_removed_from_answers(client, db, headers, own_id):
    conversation_id = started(client, headers, own_id)

    send(client, headers, conversation_id, "Yes", answer={"val\u0000ue": "peri\u0000_menopausal"})

    assert messages_by_text(db)["Yes"].answer == {"value": "peri_menopausal"}


def test_unexpected_errors_are_not_cached(db, headers, own_id, monkeypatch):
    def broken(*args):
        raise RuntimeError("Something broke, as asked.")

    monkeypatch.setattr(service, "list_conversations", broken)
    with TestClient(
        app, base_url="http://testserver/api/v1", raise_server_exceptions=False
    ) as raw_client:
        response = raw_client.get(f"/profiles/{own_id}/conversations", headers=headers)

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"


def test_streamed_replies_are_not_cached(client, headers, own_id):
    accept_consent(client, headers, own_id)
    conversation_id = started(client, headers, own_id)

    response = reply(client, headers, conversation_id)

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/event-stream")
