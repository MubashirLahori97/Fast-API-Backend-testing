"""Tests for the remote clinician chat oracle (app/oracle/clinician_chat.py)."""

import pytest

from app.core.config import settings
from app.oracle.clinician_chat import (
    CLINICIAN_MESSAGE_MAX_LENGTH,
    ClinicianChatOracle,
    context_preamble,
)
from app.oracle.contract import OracleError, ProfileContext, Turn


@pytest.fixture
def profile_context() -> ProfileContext:
    return ProfileContext(
        is_self=True,
        first_name="Alex",
        advocate_first_name="Alex",
        relationship=None,
        age_group="adult",
        sex_at_birth="female",
        gender_identity="woman",
        gender_identity_other=None,
        pronouns="she_her",
        pronouns_other=None,
    )


def test_clinician_oracle_initialization():
    oracle = ClinicianChatOracle()
    assert oracle is not None


def test_context_preamble_contains_profile_info(profile_context):
    preamble = context_preamble(profile_context)
    assert "Alex" in preamble
    assert "adult" in preamble
    assert "she/her" in preamble


def test_stream_reply_requires_conversation_id(profile_context):
    oracle = ClinicianChatOracle()
    history = [Turn(role="client", text="Hello")]
    with pytest.raises(OracleError, match="conversation id"):
        list(oracle.stream_reply(profile_context, history, [], conversation_id=None))


def test_stream_reply_requires_client_message(profile_context):
    oracle = ClinicianChatOracle()
    history = [Turn(role="oracle", text="Hello")]
    with pytest.raises(OracleError, match="no client message"):
        list(oracle.stream_reply(profile_context, history, [], conversation_id="conv-12345678"))


def test_message_too_long_raises_oracle_error(profile_context):
    oracle = ClinicianChatOracle()
    too_long = "x" * (CLINICIAN_MESSAGE_MAX_LENGTH + 1)
    history = [Turn(role="client", text=too_long)]
    with pytest.raises(OracleError, match="too long"):
        list(oracle.stream_reply(profile_context, history, [], conversation_id="conv-12345678"))
