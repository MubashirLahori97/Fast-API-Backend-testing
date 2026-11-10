"""Verification codes, shared by stories 1.1 (sign-up) and 1.2 (2FA at sign-in).

The two stories word the wrong-code and expired-code messages differently; each code gets its
own story's wording (docs/PLAN.md, question 31).
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.models import PendingSignUp, VerificationChallenge
from app.core.audit import AuditEvent
from app.core.config import Settings, settings
from tests.helpers import PASSWORD, last_code
from tests.test_sign_up import VALID, purge

# Story 1.2 (sign-in codes)
CODE_WRONG = "That code doesn’t match. Please check your email and try again."
CODE_EXPIRED = "This code has expired. Please request a new one."
# Story 1.1 (sign-up codes)
SIGN_UP_CODE_WRONG = "That code isn’t right. Please try again."
SIGN_UP_CODE_EXPIRED = "Please request a new code."
# Resending
RESEND_LIMIT = "Please sign in again to get a new code."
SIGN_UP_RESEND_LIMIT = "Please sign up again to get a new code."
RESEND_TOO_SOON = "Please wait a minute before asking for a new code."
TOO_MANY_CODES = "You’ve asked for too many codes. Please wait an hour and try again."
# Not in the stories: the per-IP limit's text (docs/PLAN.md, R1).
TOO_MANY_ATTEMPTS = "Too many attempts. Please wait a few minutes and try again."


@pytest.fixture
def challenge(client, make_user) -> dict:
    """A sign-in on a new device, waiting for its code."""
    make_user()
    return client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    ).json()


@pytest.fixture
def sign_up_challenge(client) -> dict:
    """A new sign-up, waiting for the code that verifies the email."""
    return client.post("/auth/signup", json=VALID).json()


def load(db, challenge: dict) -> VerificationChallenge:
    return db.get(VerificationChallenge, uuid.UUID(challenge["challenge_id"]))


def verify(client, challenge: dict, code: str):
    return client.post(
        "/auth/verify", json={"challenge_id": challenge["challenge_id"], "code": code}
    )


def resend(client, db, challenge: dict):
    """Asks for a new code, as if the 60 seconds had passed."""
    load(db, challenge).sent_at = datetime.now(UTC) - timedelta(seconds=61)
    db.commit()
    return client.post("/auth/verify/resend", json={"challenge_id": challenge["challenge_id"]})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# Sign-in codes (story 1.2)


def test_wrong_code_is_rejected(client, challenge, email_sender):
    response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "code_wrong",
        "message": CODE_WRONG,
        "field": "code",
    }


def test_code_stops_working_after_too_many_wrong_tries(client, challenge, email_sender):
    code = last_code(email_sender)
    for _ in range(settings.code_max_attempts):
        verify(client, challenge, wrong(code))

    response = verify(client, challenge, code)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == CODE_EXPIRED


@pytest.mark.parametrize(
    ("started_by", "expired"),
    [("challenge", CODE_EXPIRED), ("sign_up_challenge", SIGN_UP_CODE_EXPIRED)],
    ids=["sign-in", "sign-up"],
)
def test_fifth_wrong_code_says_to_request_a_new_one(
    request, client, email_sender, started_by, expired
):
    started = request.getfixturevalue(started_by)
    code = last_code(email_sender)
    for _ in range(settings.code_max_attempts - 1):
        assert verify(client, started, wrong(code)).json()["error"]["code"] == "code_wrong"

    response = verify(client, started, wrong(code))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "code_expired", "message": expired, "field": "code"}


def test_expired_code_is_rejected(client, db, challenge, email_sender):
    load(db, challenge).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = verify(client, challenge, last_code(email_sender))

    assert response.status_code == 400
    assert response.json()["error"]["message"] == CODE_EXPIRED


def test_code_works_only_once(client, challenge, email_sender):
    code = last_code(email_sender)
    assert verify(client, challenge, code).status_code == 200

    response = verify(client, challenge, code)

    assert response.json()["error"]["message"] == CODE_EXPIRED


def test_unknown_challenge_gets_the_expired_message(client):
    response = verify(client, {"challenge_id": str(uuid.uuid4())}, "123456")

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "code_expired",
        "message": CODE_EXPIRED,
        "field": "code",
    }


def test_empty_code(client, challenge):
    response = verify(client, challenge, " ")

    assert response.status_code == 422
    assert response.json()["error"]["message"] == (
        "Please enter the verification code sent to your email."
    )


# Sign-up codes (story 1.1)


def test_wrong_sign_up_code_is_rejected(client, sign_up_challenge, email_sender):
    response = verify(client, sign_up_challenge, wrong(last_code(email_sender)))

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "code_wrong",
        "message": SIGN_UP_CODE_WRONG,
        "field": "code",
    }


def test_sign_up_code_stops_working_after_5_wrong_tries(client, sign_up_challenge, email_sender):
    code = last_code(email_sender)
    for _ in range(5):
        assert verify(client, sign_up_challenge, wrong(code)).status_code == 400

    response = verify(client, sign_up_challenge, code)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "code_expired",
        "message": SIGN_UP_CODE_EXPIRED,
        "field": "code",
    }


def test_expired_sign_up_code_is_rejected(client, db, sign_up_challenge, email_sender):
    load(db, sign_up_challenge).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = verify(client, sign_up_challenge, last_code(email_sender))

    assert response.status_code == 400
    assert response.json()["error"]["message"] == SIGN_UP_CODE_EXPIRED


def test_sign_up_code_works_only_once(client, sign_up_challenge, email_sender):
    code = last_code(email_sender)
    assert verify(client, sign_up_challenge, code).status_code == 200

    response = verify(client, sign_up_challenge, code)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == SIGN_UP_CODE_EXPIRED


# Resending


def post_resend(client, challenge: dict):
    return client.post("/auth/verify/resend", json={"challenge_id": challenge["challenge_id"]})


def add_codes_sent(db, user_id, count: int) -> None:
    for _ in range(count):
        db.add(AuditEvent(action="auth.code.sent", actor_id=user_id))
    db.commit()


def test_resend_too_soon_is_refused(client, challenge):
    response = post_resend(client, challenge)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "resend_too_soon",
        "message": RESEND_TOO_SOON,
        "field": None,
    }


def test_resent_code_replaces_the_old_one(client, db, challenge, email_sender):
    old_code = last_code(email_sender)

    response = resend(client, db, challenge)

    assert response.status_code == 200
    new_code = last_code(email_sender)
    assert len(email_sender.sent) == 2
    if new_code != old_code:  # one in a million they're equal
        assert verify(client, challenge, old_code).status_code == 400
    assert verify(client, challenge, new_code).status_code == 200


@pytest.mark.parametrize("started_by", ["challenge", "sign_up_challenge"])
def test_new_code_works_after_5_wrong_tries(request, client, db, email_sender, started_by):
    started = request.getfixturevalue(started_by)
    code = last_code(email_sender)
    for _ in range(5):
        verify(client, started, wrong(code))
    assert verify(client, started, code).status_code == 400  # this code is used up

    assert resend(client, db, started).status_code == 200
    response = verify(client, started, last_code(email_sender))

    assert response.status_code == 200
    assert response.json()["status"] == "signed_in"


def test_resend_starts_a_new_count_of_wrong_tries(client, db, challenge, email_sender):
    for _ in range(3):
        verify(client, challenge, wrong(last_code(email_sender)))

    resend(client, db, challenge)

    row = load(db, challenge)
    db.refresh(row)
    assert row.attempts == 0


def test_resends_per_code_are_limited(client, db, challenge):
    row = load(db, challenge)
    row.send_count = settings.code_max_sends
    row.sent_at = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()

    response = post_resend(client, challenge)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_resends",
        "message": RESEND_LIMIT,
        "field": None,
    }


def test_resends_are_capped_per_hour(client, db, challenge):
    row = load(db, challenge)
    row.sent_at = datetime.now(UTC) - timedelta(minutes=2)
    add_codes_sent(db, row.user_id, settings.max_codes_sent_per_hour)

    response = post_resend(client, challenge)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_codes",
        "message": TOO_MANY_CODES,
        "field": None,
    }


def test_resend_of_a_used_code_asks_to_sign_in_again(client, challenge, email_sender):
    verify(client, challenge, last_code(email_sender))

    response = post_resend(client, challenge)  # also too soon: a closed challenge comes first

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "challenge_closed",
        "message": RESEND_LIMIT,
        "field": None,
    }


def test_resend_of_an_unknown_challenge_asks_to_sign_in_again(client):
    response = post_resend(client, {"challenge_id": str(uuid.uuid4())})

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "challenge_closed",
        "message": RESEND_LIMIT,
        "field": None,
    }


def test_resend_too_soon_comes_before_the_resend_limit(client, db, challenge):
    load(db, challenge).send_count = settings.code_max_sends
    db.commit()

    response = post_resend(client, challenge)

    assert response.json()["error"]["code"] == "resend_too_soon"


def test_resend_limit_comes_before_the_hourly_cap(client, db, challenge):
    row = load(db, challenge)
    row.send_count = settings.code_max_sends
    row.sent_at = datetime.now(UTC) - timedelta(minutes=2)
    add_codes_sent(db, row.user_id, settings.max_codes_sent_per_hour)

    response = post_resend(client, challenge)

    assert response.json()["error"]["code"] == "too_many_resends"


# The per-IP limit on code emails (security review): every code emailed from this IP, by a
# sign-up, a sign-in or a resend, counts towards 20 in 15 minutes.

CODE_EMAILS = [
    {"purpose": "verify_email"},
    {"purpose": "sign_in"},
    {"purpose": "sign_in", "resend": True},
]


def add_code_emails_from(db, ip: str, count: int) -> None:
    """Code emails sent from this IP for other accounts and sign-ups (no actor), so only the
    per-IP limit counts them."""
    for number in range(count):
        db.add(
            AuditEvent(
                action="auth.code.sent",
                ip_address=ip,
                details=CODE_EMAILS[number % len(CODE_EMAILS)],
            )
        )
    db.commit()


def test_resend_is_refused_after_20_code_emails_from_one_ip(client, db, challenge):
    # The sign-in's own code is the 20th.
    add_code_emails_from(db, "testclient", settings.ip_failure_limit - 1)

    response = resend(client, db, challenge)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "too_many_attempts",
        "message": TOO_MANY_ATTEMPTS,
        "field": None,
    }


def test_resend_under_the_ip_limit_is_sent(client, db, challenge, email_sender):
    add_code_emails_from(db, "testclient", settings.ip_failure_limit - 2)

    response = resend(client, db, challenge)

    assert response.status_code == 200
    assert len(email_sender.sent) == 2


def test_resend_ip_limit_counts_only_this_ip(client, db, challenge):
    add_code_emails_from(db, "203.0.113.5", settings.ip_failure_limit)

    response = resend(client, db, challenge)

    assert response.status_code == 200


def test_resend_refused_by_the_ip_limit_is_audited(client, db, challenge):
    add_code_emails_from(db, "testclient", settings.ip_failure_limit - 1)

    resend(client, db, challenge)

    [event] = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.rate_limited"))
    assert event.details == {"limited_action": "auth.code.sent"}


def test_resend_ip_limit_counts_sign_up_codes_too(client, db, sign_up_challenge):
    add_code_emails_from(db, "testclient", settings.ip_failure_limit - 1)

    response = resend(client, db, sign_up_challenge)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


def test_a_new_sign_in_closes_the_previous_code(client, challenge, email_sender):
    first_code = last_code(email_sender)
    client.post("/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD})

    response = verify(client, challenge, first_code)

    assert response.json()["error"]["message"] == CODE_EXPIRED


# Resending a sign-up code (story 1.1). The texts for a code that can't be resent aren't in
# the stories (docs/PLAN.md, R1).


def pending_of(db, challenge: dict) -> PendingSignUp:
    return db.get(PendingSignUp, load(db, challenge).pending_sign_up_id)


def sign_up_closed(code: str) -> dict:
    return {"code": code, "message": SIGN_UP_RESEND_LIMIT, "field": None}


def test_resent_sign_up_code_replaces_the_old_one(client, db, sign_up_challenge, email_sender):
    old_code = last_code(email_sender)

    response = resend(client, db, sign_up_challenge)

    assert response.status_code == 200
    assert response.json()["purpose"] == "verify_email"
    new_code = last_code(email_sender)
    if new_code != old_code:  # one in a million they're equal
        assert verify(client, sign_up_challenge, old_code).status_code == 400
    assert verify(client, sign_up_challenge, new_code).json()["status"] == "signed_in"


def test_resent_sign_up_code_is_counted_by_its_attempt(client, db, sign_up_challenge):
    pending_id = load(db, sign_up_challenge).pending_sign_up_id

    resend(client, db, sign_up_challenge)

    resent = [
        (event.actor_id, event.details)
        for event in db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.code.sent"))
        if event.details.get("resend")
    ]
    assert resent == [(pending_id, {"purpose": "verify_email", "resend": True})]


def test_resending_a_sign_up_code_keeps_the_attempt_60_minutes_more(client, db, sign_up_challenge):
    pending = pending_of(db, sign_up_challenge)
    pending.expires_at = datetime.now(UTC) + timedelta(minutes=1)
    db.commit()

    resend(client, db, sign_up_challenge)

    db.refresh(pending)
    expected = datetime.now(UTC) + timedelta(minutes=settings.pending_sign_up_minutes)
    assert abs(pending.expires_at - expected) < timedelta(minutes=1)


def test_resending_a_sign_up_code_keeps_a_later_expiry(client, db, sign_up_challenge):
    pending = pending_of(db, sign_up_challenge)
    later = datetime.now(UTC) + timedelta(minutes=settings.pending_sign_up_minutes + 30)
    pending.expires_at = later
    db.commit()

    resend(client, db, sign_up_challenge)

    db.refresh(pending)
    assert pending.expires_at == later


def test_sign_up_resends_per_code_are_limited(client, db, sign_up_challenge):
    row = load(db, sign_up_challenge)
    row.send_count = settings.code_max_sends
    row.sent_at = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()

    response = post_resend(client, sign_up_challenge)

    assert response.status_code == 429
    assert response.json()["error"] == sign_up_closed("too_many_resends")


def test_resend_of_a_used_sign_up_code_asks_to_sign_up_again(
    client, sign_up_challenge, email_sender
):
    verify(client, sign_up_challenge, last_code(email_sender))

    response = post_resend(client, sign_up_challenge)

    assert response.status_code == 400
    assert response.json()["error"] == sign_up_closed("challenge_closed")


def test_resend_of_a_purged_sign_up_code_asks_to_sign_up_again(client, db, sign_up_challenge):
    pending = pending_of(db, sign_up_challenge)
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    purge(db, pending.id)

    response = resend(client, db, sign_up_challenge)

    assert response.status_code == 400
    assert response.json()["error"] == sign_up_closed("challenge_closed")


def test_resend_of_another_attempts_code_after_the_account_exists_asks_to_sign_up_again(
    client, db, sign_up_challenge, email_sender
):
    newer = client.post("/auth/signup", json=VALID).json()
    verify(client, newer, last_code(email_sender))

    response = resend(client, db, sign_up_challenge)

    assert response.status_code == 400
    assert response.json()["error"] == sign_up_closed("challenge_closed")


# The database's own checks


def test_database_refuses_a_code_with_two_owners(db, make_user):
    user = make_user()
    pending = PendingSignUp(
        email="maria@example.com",
        first_name="Maria",
        date_of_birth=date(1990, 1, 1),
        country="US",
        state="NY",
        password_hash="not a real hash",
        policy_version_ids=[],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(pending)
    db.flush()
    now = datetime.now(UTC)
    db.add(
        VerificationChallenge(
            user_id=user.id,
            pending_sign_up_id=pending.id,
            purpose="verify_email",
            code_hash="not a real hash",
            sent_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


# The email


@pytest.mark.parametrize("started_by", ["challenge", "sign_up_challenge"])
def test_code_email_names_your_oracle(request, email_sender, started_by):
    request.getfixturevalue(started_by)
    email = email_sender.sent[-1]

    assert "Your Oracle" in email.body
    assert "Clinician" not in email.body


def test_emails_come_from_your_oracle():
    assert Settings.model_fields["email_from"].default == (
        "Your Oracle <no-reply@genesishealth.local>"
    )


# The resend countdown (stories 1.1 and 1.2: a new code after 60 seconds)


def test_sign_in_code_says_when_it_can_be_resent(challenge):
    assert challenge["resend_after_seconds"] == 60


def test_sign_up_code_says_when_it_can_be_resent(sign_up_challenge):
    assert sign_up_challenge["resend_after_seconds"] == 60


def test_resent_code_starts_the_countdown_again(client, db, challenge):
    response = resend(client, db, challenge)

    assert response.status_code == 200
    assert response.json()["resend_after_seconds"] == 60


def test_countdown_follows_the_setting(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "code_resend_seconds", 90)
    make_user()

    body = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    ).json()

    assert body["resend_after_seconds"] == 90
