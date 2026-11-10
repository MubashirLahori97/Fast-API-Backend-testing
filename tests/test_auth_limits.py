"""Limits that stop guessing codes and passwords (from the Phase 1 security review)."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import service as auth_service
from app.auth.models import PendingSignUp, User, VerificationChallenge
from app.auth.service import LOCKED_UNTIL_RESET
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.errors import AppError
from app.main import app
from tests.helpers import PASSWORD, last_code, last_reset_token
from tests.test_sign_up import VALID

CODE_EXPIRED = "This code has expired. Please request a new one."
LOCKED = {
    "code": "account_locked",
    "message": (
        "Your account has been temporarily locked after too many attempts. "
        "Please reset your password to continue."
    ),
    "field": None,
}


def start_sign_in(client) -> dict:
    return client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    ).json()


def verify(client, challenge: dict, code: str):
    return client.post(
        "/auth/verify", json={"challenge_id": challenge["challenge_id"], "code": code}
    )


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def load(db, challenge: dict) -> VerificationChallenge:
    return db.get(VerificationChallenge, uuid.UUID(challenge["challenge_id"]))


def add_events(db, user, action: str, count: int, hours_ago: float = 0) -> None:
    """Earlier events of this kind for the user, as if they'd happened `hours_ago`."""
    occurred_at = datetime.now(UTC) - timedelta(hours=hours_ago, minutes=1)
    for _ in range(count):
        db.add(AuditEvent(action=action, actor_id=user.id, occurred_at=occurred_at))
    db.commit()


def code_events(db, action: str) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


def lock_details(db, user) -> list:
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_id == user.id, AuditEvent.action == "auth.account_locked"
        )
    )
    return [event.details for event in events]


def test_resent_codes_still_count_towards_the_hourly_lock(client, db, make_user, email_sender):
    """A resend gives a fresh count of tries, but the wrong codes before and after it add up
    to max_failed_codes_per_hour (10), which locks the account."""
    make_user()
    challenge = start_sign_in(client)
    for _ in range(settings.code_max_attempts):  # 5 wrong: this code is used up
        verify(client, challenge, wrong(last_code(email_sender)))
    row = db.get(VerificationChallenge, uuid.UUID(challenge["challenge_id"]))
    row.sent_at = datetime.now(UTC) - timedelta(seconds=61)
    db.commit()
    client.post("/auth/verify/resend", json={"challenge_id": challenge["challenge_id"]})
    for _ in range(settings.max_failed_codes_per_hour - settings.code_max_attempts - 1):
        assert verify(client, challenge, wrong(last_code(email_sender))).status_code == 400

    response = verify(client, challenge, wrong(last_code(email_sender)))  # the 10th wrong code

    assert response.status_code == 423
    assert response.json()["error"]["code"] == "account_locked"
    after = client.post("/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD})
    assert after.status_code == 423


def test_wrong_codes_across_sign_ins_lock_the_account(client, make_user, email_sender):
    make_user()
    for _ in range(settings.max_failed_codes_per_hour):
        challenge = start_sign_in(client)
        response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 423
    after = client.post("/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD})
    assert after.status_code == 423


def test_code_emails_are_capped_per_account(client, db, make_user):
    user = make_user()
    for _ in range(settings.max_codes_sent_per_hour):
        db.add(AuditEvent(action="auth.code.sent", actor_id=user.id))
    db.commit()

    response = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_codes"


def test_password_reset_closes_an_open_sign_in_code(client, make_user, email_sender):
    make_user()
    challenge = start_sign_in(client)
    code = last_code(email_sender)
    client.post("/auth/password/forgot", json={"email": "sarah@example.com"})
    client.post(
        "/auth/password/reset",
        json={
            "token": last_reset_token(email_sender),
            "new_password": "Renewal#2027",
            "confirm_password": "Renewal#2027",
        },
    )

    response = verify(client, challenge, code)

    assert response.json()["error"]["message"] == CODE_EXPIRED


def test_sign_in_code_email_warns_the_password_was_used(client, make_user, email_sender):
    make_user()
    start_sign_in(client)

    assert "with your password" in email_sender.sent[-1].body


def test_code_email_cap_is_audited_at_sign_in(client, db, make_user):
    user = make_user()
    add_events(db, user, "auth.code.sent", settings.max_codes_sent_per_hour)

    client.post("/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD})

    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.code.limited")).one()
    assert (event.actor_id, event.details) == (user.id, {"purpose": "sign_in"})


# Sign-up attempts (story 1.1). Each sign-up is its own attempt, so nobody can block someone
# else's sign-up: there's no per-email lock, only a cap on attempts per email and IP address,
# and the per-IP limit on wrong codes (docs/PLAN.md, R1).

TOO_MANY_CODES = {
    "code": "too_many_codes",
    "message": "You’ve asked for too many codes. Please wait an hour and try again.",
    "field": None,
}
TOO_MANY_ATTEMPTS = {
    "code": "too_many_attempts",
    "message": "Too many attempts. Please wait a few minutes and try again.",
    "field": None,
}


def sign_up_attempts(client, count: int, **changes) -> None:
    for _ in range(count):
        assert client.post("/auth/signup", json={**VALID, **changes}).status_code == 201


def attempt_count(db) -> int:
    return db.scalar(select(func.count()).select_from(PendingSignUp))


def test_sign_up_attempts_per_email_and_ip_are_capped(client):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)

    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 429
    assert response.json()["error"] == TOO_MANY_CODES


def test_capped_sign_up_saves_nothing(client, db, email_sender):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)
    started_before = len(code_events(db, "auth.sign_up.started"))

    client.post("/auth/signup", json=VALID)

    assert attempt_count(db) == settings.max_sign_ups_per_email_per_hour
    assert len(email_sender.sent) == settings.max_sign_ups_per_email_per_hour
    assert len(code_events(db, "auth.sign_up.started")) == started_before


def test_code_email_cap_is_audited_at_sign_up(client, db):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)

    client.post("/auth/signup", json=VALID)

    [event] = code_events(db, "auth.code.limited")
    assert (event.actor_id, event.details) == (None, {"purpose": "verify_email"})


def test_sign_up_cap_doesnt_apply_from_another_ip_address(client):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)

    with TestClient(
        app, base_url="http://testserver/api/v1", client=("203.0.113.5", 50000)
    ) as elsewhere:
        response = elsewhere.post("/auth/signup", json=VALID)

    assert response.status_code == 201


def test_sign_up_cap_doesnt_apply_to_another_email(client):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)

    response = client.post("/auth/signup", json={**VALID, "email": "maria@example.com"})

    assert response.status_code == 201


def test_sign_up_cap_counts_only_the_last_hour(client, db):
    sign_up_attempts(client, settings.max_sign_ups_per_email_per_hour)
    for pending in db.scalars(select(PendingSignUp)):
        pending.created_at = datetime.now(UTC) - timedelta(minutes=61)
    db.commit()

    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 201


def test_wrong_sign_up_code_is_recorded_against_its_attempt(client, db, email_sender):
    challenge = client.post("/auth/signup", json=VALID).json()

    verify(client, challenge, wrong(last_code(email_sender)))

    pending_id = db.scalars(select(PendingSignUp.id)).one()
    [event] = code_events(db, "auth.code.failed")
    assert (event.actor_id, event.details) == (pending_id, {"reason": "wrong"})


def test_wrong_codes_across_sign_up_attempts_lock_nothing(client, db, email_sender):
    """10 wrong codes in an hour would lock an account; a sign-up has no lock to set off."""
    for _ in range(settings.max_failed_codes_per_hour // settings.code_max_attempts):
        challenge = client.post("/auth/signup", json=VALID).json()
        code = last_code(email_sender)
        for _ in range(settings.code_max_attempts):
            assert verify(client, challenge, wrong(code)).status_code == 400
    challenge = client.post("/auth/signup", json=VALID).json()

    response = verify(client, challenge, last_code(email_sender))

    assert response.status_code == 200
    assert response.json()["status"] == "signed_in"
    assert code_events(db, "auth.sign_up.locked") == []


# The per-IP limits count addresses as app.core.audit.client_ip stores them: an IPv6 address
# by its /64 block (security review).


def client_at(host: str) -> TestClient:
    """A client calling from another address. The client fixture's dependency overrides
    apply to it too, so use both together."""
    return TestClient(app, base_url="http://testserver/api/v1", client=(host, 50000))


def unknown_sign_in(api):
    return api.post("/auth/signin", json={"email": "nobody@example.com", "password": PASSWORD})


def test_addresses_in_one_ipv6_64_block_share_the_ip_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "ip_failure_limit", 2)

    with client_at("2001:db8:1:2::1") as first, client_at("2001:db8:1:2:ffff::9") as second:
        for _ in range(2):
            assert unknown_sign_in(first).status_code == 401
        response = unknown_sign_in(second)

    assert response.status_code == 429
    assert response.json()["error"] == TOO_MANY_ATTEMPTS


def test_another_ipv6_64_block_has_its_own_ip_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "ip_failure_limit", 2)

    with client_at("2001:db8:1:2::1") as first, client_at("2001:db8:1:3::1") as other:
        for _ in range(2):
            assert unknown_sign_in(first).status_code == 401
        response = unknown_sign_in(other)

    assert response.status_code == 401


# A request with no client address (only possible behind a proxy that hides it)

NO_CLIENT = SimpleNamespace(client=None, headers={})


def test_ip_limit_without_a_client_address_fails_closed_in_production(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(AppError) as refused:
        auth_service._check_ip_limit(db, NO_CLIENT, "auth.sign_in.failed")

    assert (refused.value.status_code, refused.value.code, refused.value.message) == (
        503,
        "save_failed",
        "We couldn’t do that just now. Please try again.",
    )


@pytest.mark.parametrize("environment", ["development", "test"])
def test_ip_limit_without_a_client_address_is_skipped_outside_production(
    db, monkeypatch, environment
):
    monkeypatch.setattr(settings, "environment", environment)

    assert auth_service._check_ip_limit(db, NO_CLIENT, "auth.sign_in.failed") is None


def test_ip_limit_stops_guessing_sign_up_codes(client, db, email_sender):
    challenge = client.post("/auth/signup", json=VALID).json()
    half = settings.ip_failure_limit // 2
    for action in ["auth.code.failed"] * half + ["auth.code.rejected"] * (
        settings.ip_failure_limit - half
    ):
        db.add(AuditEvent(action=action, ip_address="testclient"))
    db.commit()

    response = verify(client, challenge, last_code(email_sender))

    assert response.status_code == 429
    assert response.json()["error"] == TOO_MANY_ATTEMPTS
    assert db.scalars(select(User)).first() is None


# A locked account, and the hourly and daily limits on wrong codes


@pytest.mark.parametrize("right_code", [False, True], ids=["wrong-code", "right-code"])
def test_locked_account_is_refused_before_the_code_is_checked(
    client, db, make_user, email_sender, right_code
):
    user = make_user()
    challenge = start_sign_in(client)
    user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()
    code = last_code(email_sender)

    response = verify(client, challenge, code if right_code else wrong(code))

    assert response.status_code == 423
    assert response.json()["error"] == LOCKED
    row = load(db, challenge)
    db.refresh(row)
    assert row.attempts == 0


def test_hourly_code_lock_is_audited(client, db, make_user, email_sender):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_hour - 1)

    response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 423
    assert lock_details(db, user) == [{"reason": "wrong_codes", "until_reset": False}]


def test_hourly_code_lock_runs_out_after_30_minutes(
    client, db, make_user, email_sender, monkeypatch
):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_hour - 1)
    verify(client, challenge, wrong(last_code(email_sender)))
    later = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes + 1)
    monkeypatch.setattr(auth_service, "_now", lambda: later)

    response = start_sign_in(client)

    assert response["status"] == "verification_required"


def test_30_wrong_codes_in_a_day_lock_the_account_until_a_reset(
    client, db, make_user, email_sender
):
    user = make_user()
    challenge = start_sign_in(client)
    # Earlier today, outside the hourly window, so only the daily limit is reached.
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_day - 1, hours_ago=2)

    response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 423
    assert response.json()["error"] == LOCKED
    db.refresh(user)
    assert user.locked_until == LOCKED_UNTIL_RESET
    row = load(db, challenge)
    db.refresh(row)
    assert row.used_at is not None  # the challenge is closed


def test_daily_code_lock_is_audited(client, db, make_user, email_sender):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_day - 1, hours_ago=2)

    verify(client, challenge, wrong(last_code(email_sender)))

    assert lock_details(db, user) == [{"reason": "wrong_codes", "until_reset": True}]


def test_daily_code_lock_outlasts_the_30_minute_lock(
    client, db, make_user, email_sender, monkeypatch
):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_day - 1, hours_ago=2)
    verify(client, challenge, wrong(last_code(email_sender)))
    later = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes + 1)
    monkeypatch.setattr(auth_service, "_now", lambda: later)

    response = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    )

    assert response.status_code == 423
    assert response.json()["error"] == LOCKED


def reset_password(client, email_sender, new_password: str = "Renewal#2027") -> None:
    client.post("/auth/password/forgot", json={"email": "sarah@example.com"})
    response = client.post(
        "/auth/password/reset",
        json={
            "token": last_reset_token(email_sender),
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("limit", "hours_ago"),
    [("max_failed_codes_per_hour", 0), ("max_failed_codes_per_day", 2)],
    ids=["hourly-lock", "daily-lock"],
)
def test_password_reset_ends_the_code_lock_and_its_count(
    client, db, make_user, email_sender, limit, hours_ago
):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", getattr(settings, limit) - 1, hours_ago=hours_ago)
    assert verify(client, challenge, wrong(last_code(email_sender))).status_code == 423
    reset_password(client, email_sender)
    db.refresh(user)
    assert abs(user.password_changed_at - datetime.now(UTC)) < timedelta(minutes=1)
    challenge = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": "Renewal#2027"}
    ).json()
    assert challenge["status"] == "verification_required"

    # The wrong codes from before the reset no longer count, so one more doesn't lock again.
    response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "code_wrong"


def test_wrong_codes_older_than_a_day_dont_count(client, db, make_user, email_sender):
    user = make_user()
    challenge = start_sign_in(client)
    add_events(db, user, "auth.code.failed", settings.max_failed_codes_per_day - 1, hours_ago=25)

    response = verify(client, challenge, wrong(last_code(email_sender)))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "code_wrong"


# Codes refused before they're compared are "rejected"; only wrong guesses are "failed" and
# count towards the account's code locks.


def test_wrong_code_is_recorded_as_failed(client, db, make_user, email_sender):
    user = make_user()
    challenge = start_sign_in(client)

    verify(client, challenge, wrong(last_code(email_sender)))

    [event] = code_events(db, "auth.code.failed")
    assert (event.actor_id, event.details) == (user.id, {"reason": "wrong"})
    assert code_events(db, "auth.code.rejected") == []


@pytest.mark.parametrize(
    "refused_because", ["expired", "too_many_attempts", "locked", "deactivated"]
)
def test_code_refused_before_comparing_is_recorded_as_rejected(
    client, db, make_user, email_sender, refused_because
):
    user = make_user()
    challenge = start_sign_in(client)
    code = last_code(email_sender)
    if refused_because == "expired":
        load(db, challenge).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif refused_because == "too_many_attempts":
        load(db, challenge).attempts = settings.code_max_attempts
    elif refused_because == "locked":
        user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    else:
        user.status = "deactivated"  # refused after the right code
    db.commit()

    verify(client, challenge, code)

    [event] = code_events(db, "auth.code.rejected")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        None,
        "user",
        str(user.id),
        {"reason": refused_because},
    )
    assert code_events(db, "auth.code.failed") == []


def test_unknown_challenge_is_recorded_as_rejected_with_no_account(client, db):
    verify(client, {"challenge_id": str(uuid.uuid4())}, "123456")

    [event] = code_events(db, "auth.code.rejected")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        None,
        None,
        None,
        {"reason": "unknown_challenge"},
    )


def test_replaying_a_closed_challenge_doesnt_lock_the_account(
    client, db, make_user, email_sender, monkeypatch
):
    # One IP would hit its own limit after 20 tries; the account limits are what's tested here.
    monkeypatch.setattr(settings, "ip_failure_limit", 1000)
    user = make_user()
    challenge = start_sign_in(client)
    code = last_code(email_sender)
    assert verify(client, challenge, code).status_code == 200  # this challenge is now closed
    for _ in range(settings.max_failed_codes_per_day + 1):
        assert verify(client, challenge, code).json()["error"]["code"] == "code_expired"
    db.refresh(user)
    assert user.locked_until is None
    new_challenge = start_sign_in(client)

    response = verify(client, new_challenge, wrong(last_code(email_sender)))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "code_wrong"


def test_ip_limit_on_verify_counts_wrong_and_rejected_codes_together(client, db, make_user):
    make_user()
    challenge = start_sign_in(client)
    half = settings.ip_failure_limit // 2
    for action in ["auth.code.failed"] * half + ["auth.code.rejected"] * (
        settings.ip_failure_limit - half
    ):
        db.add(AuditEvent(action=action, ip_address="testclient"))
    db.commit()

    response = verify(client, challenge, "123456")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
