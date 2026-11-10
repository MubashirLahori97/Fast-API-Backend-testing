"""Story 1.2: Sign In (2FA code)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.models import TrustedDevice, UserSession
from app.auth.security import hash_secret
from app.core.audit import AuditEvent
from app.core.config import settings
from tests.helpers import PASSWORD, bearer, last_code

INVALID = {
    "code": "invalid_credentials",
    "message": "Incorrect email or password. Please try again.",
    "field": None,
}
LOCKED = (
    "Your account has been temporarily locked after too many attempts. "
    "Please reset your password to continue."
)
DEACTIVATED = "Your account has been deactivated. Please contact the support team for help."


def post_sign_in(client, email="sarah@example.com", password=PASSWORD, device_token=None):
    return client.post(
        "/auth/signin", json={"email": email, "password": password, "device_token": device_token}
    )


def test_new_device_needs_a_code(client, make_user, email_sender):
    make_user()

    response = post_sign_in(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verification_required"
    assert body["purpose"] == "sign_in"
    assert email_sender.sent[-1].to == "sarah@example.com"


def test_code_signs_in_and_trusts_the_device(client, make_user, sign_in):
    make_user()

    body = sign_in()

    assert body["status"] == "signed_in"
    assert body["device_token"]
    assert client.get("/me", headers=bearer(body["access_token"])).status_code == 200


def test_trusted_device_skips_the_code(client, make_user, sign_in, email_sender):
    make_user()
    device_token = sign_in()["device_token"]
    emails_before = len(email_sender.sent)

    body = post_sign_in(client, device_token=device_token).json()

    assert body["status"] == "signed_in"
    assert len(email_sender.sent) == emails_before


def test_expired_trusted_device_needs_a_code_again(client, db, make_user, sign_in):
    make_user()
    device_token = sign_in()["device_token"]
    device = db.scalar(
        select(TrustedDevice).where(TrustedDevice.token_hash == hash_secret(device_token))
    )
    device.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    body = post_sign_in(client, device_token=device_token).json()

    assert body["status"] == "verification_required"


def test_another_clients_device_token_doesnt_skip_the_code(client, make_user, sign_in):
    make_user(email="sarah@example.com")
    make_user(email="maria@example.com")
    marias_device = sign_in(email="maria@example.com")["device_token"]

    body = post_sign_in(client, device_token=marias_device).json()

    assert body["status"] == "verification_required"


def test_email_is_not_case_sensitive(client, make_user):
    make_user()

    assert post_sign_in(client, email="SARAH@Example.com").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(client, make_user):
    make_user()

    wrong_password = post_sign_in(client, password="Wrong!2026")
    unknown_email = post_sign_in(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"] == unknown_email.json()["error"] == INVALID


def test_three_wrong_passwords_lock_the_account(client, make_user):
    make_user()
    for _ in range(settings.max_failed_sign_ins - 1):
        assert post_sign_in(client, password="Wrong!2026").status_code == 401

    response = post_sign_in(client, password="Wrong!2026")

    assert response.status_code == 423
    assert response.json()["error"]["message"] == LOCKED


def test_locked_account_refuses_even_the_right_password(client, make_user):
    make_user(locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_sign_ins=3)

    response = post_sign_in(client)

    assert response.status_code == 423


def test_lock_runs_out(client, make_user):
    make_user(locked_until=datetime.now(UTC) - timedelta(seconds=1), failed_sign_ins=3)

    response = post_sign_in(client)

    assert response.json()["status"] == "verification_required"


def test_successful_sign_in_resets_the_failure_count(client, db, make_user):
    user = make_user()
    post_sign_in(client, password="Wrong!2026")
    post_sign_in(client)

    db.refresh(user)
    assert user.failed_sign_ins == 0


def test_deactivated_account_is_told_only_with_the_right_password(client, make_user):
    make_user(status="deactivated")

    right = post_sign_in(client)
    wrong = post_sign_in(client, password="Wrong!2026")

    assert right.status_code == 403
    assert right.json()["error"] == {
        "code": "account_deactivated",
        "message": DEACTIVATED,
        "field": None,
    }
    assert wrong.json()["error"] == INVALID


@pytest.mark.parametrize(
    ("email", "password", "field", "message"),
    [
        ("", PASSWORD, "email", "Email is required."),
        ("sarah@", PASSWORD, "email", "Please enter a valid email address."),
        ("sarah@example.com", "", "password", "Password is required."),
    ],
    ids=["email-empty", "email-invalid", "password-empty"],
)
def test_sign_in_validation(client, email, password, field, message):
    response = post_sign_in(client, email=email, password=password)

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)


def test_sign_in_attempts_are_audited(client, db, make_user, sign_in):
    user = make_user()
    post_sign_in(client, password="Wrong!2026")
    sign_in()

    actions = list(db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id)))
    assert "auth.sign_in.failed" in actions
    assert "auth.sign_in.succeeded" in actions


def test_too_many_failures_from_one_ip_are_blocked(client, db, make_user):
    make_user()
    for _ in range(settings.ip_failure_limit):
        db.add(AuditEvent(action="auth.sign_in.failed", ip_address="testclient"))
    db.commit()

    response = post_sign_in(client)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


def test_a_new_device_needs_a_code_even_when_another_is_trusted(client, make_user, sign_in):
    make_user()
    sign_in()  # this device is now trusted

    body = post_sign_in(client).json()  # a second device, with no device token

    assert body["status"] == "verification_required"


def test_locked_account_with_the_right_password_gets_the_lock_message(client, make_user):
    make_user(locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_sign_ins=3)

    assert post_sign_in(client).json()["error"]["message"] == LOCKED


def test_lock_and_blocked_attempts_are_audited(client, db, make_user):
    user = make_user()
    for _ in range(settings.max_failed_sign_ins + 1):
        post_sign_in(client, password="Wrong!2026")

    actions = list(db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id)))
    assert "auth.account_locked" in actions
    assert "auth.sign_in.blocked" in actions


def test_password_lock_is_audited_with_its_reason(client, db, make_user):
    user = make_user()
    for _ in range(settings.max_failed_sign_ins):
        post_sign_in(client, password="Wrong!2026")

    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_id == user.id, AuditEvent.action == "auth.account_locked"
        )
    ).one()
    assert event.details == {"reason": "wrong_passwords", "until_reset": False}


def test_rate_limited_attempts_are_audited(client, db, make_user):
    make_user()
    for _ in range(settings.ip_failure_limit):
        db.add(AuditEvent(action="auth.sign_in.failed", ip_address="testclient"))
    db.commit()

    post_sign_in(client)

    limited = select(AuditEvent).where(AuditEvent.action == "auth.rate_limited")
    assert db.scalars(limited).first() is not None


# The platform: web (the default) or mobile, stored on the session (story 1.2)

BROWSER_HEADERS = [{"Origin": "http://localhost:5173"}, {"Sec-Fetch-Mode": "cors"}]


def session_for(db, token: str) -> UserSession:
    return db.scalar(select(UserSession).where(UserSession.token_hash == hash_secret(token)))


def device_for(db, device_token: str) -> TrustedDevice:
    return db.scalar(
        select(TrustedDevice).where(TrustedDevice.token_hash == hash_secret(device_token))
    )


def sign_in_audit_details(db, user) -> list:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.actor_id == user.id, AuditEvent.action == "auth.sign_in.succeeded")
        .order_by(AuditEvent.occurred_at)
    )
    return [event.details for event in events]


def trusted_sign_in(client, device_token: str, platform: str, headers: dict | None = None):
    return client.post(
        "/auth/signin",
        headers=headers,
        json={
            "email": "sarah@example.com",
            "password": PASSWORD,
            "device_token": device_token,
            "platform": platform,
        },
    ).json()


def verify_on(client, email_sender, platform: str, headers: dict | None = None) -> dict:
    challenge = post_sign_in(client).json()
    return client.post(
        "/auth/verify",
        headers=headers,
        json={
            "challenge_id": challenge["challenge_id"],
            "code": last_code(email_sender),
            "platform": platform,
        },
    ).json()


def test_session_is_a_web_one_by_default(client, db, make_user, sign_in):
    make_user()

    token = sign_in()["access_token"]

    assert session_for(db, token).platform == "web"


def test_verify_records_a_mobile_session(client, db, make_user, sign_in):
    make_user()

    token = sign_in(platform="mobile")["access_token"]

    assert session_for(db, token).platform == "mobile"


@pytest.mark.parametrize("platform", ["web", "mobile"])
def test_verify_trusts_the_device_with_its_platform(client, db, make_user, sign_in, platform):
    make_user()

    device_token = sign_in(platform=platform)["device_token"]

    assert device_for(db, device_token).platform == platform


@pytest.mark.parametrize(
    ("verified_on", "declared", "hours"),
    [("web", "mobile", 12), ("mobile", "web", 30 * 24)],
    ids=["web-device-claims-mobile", "mobile-device-claims-web"],
)
def test_trusted_device_sign_in_uses_the_devices_platform(
    client, db, make_user, sign_in, verified_on, declared, hours
):
    make_user()
    device_token = sign_in(platform=verified_on)["device_token"]

    body = trusted_sign_in(client, device_token, declared)

    assert body["status"] == "signed_in"
    session = session_for(db, body["access_token"])
    assert session.platform == verified_on
    expected = datetime.now(UTC) + timedelta(hours=hours)
    assert abs(session.expires_at - expected) < timedelta(minutes=1)


@pytest.mark.parametrize("headers", BROWSER_HEADERS, ids=["origin", "sec-fetch-mode"])
def test_browser_gets_a_web_session_at_verify_even_if_it_claims_mobile(
    client, db, make_user, email_sender, headers
):
    make_user()

    body = verify_on(client, email_sender, "mobile", headers)

    assert body["status"] == "signed_in"
    assert session_for(db, body["access_token"]).platform == "web"
    assert device_for(db, body["device_token"]).platform == "web"


@pytest.mark.parametrize("headers", BROWSER_HEADERS, ids=["origin", "sec-fetch-mode"])
def test_browser_gets_a_web_session_on_a_mobile_device_token(
    client, db, make_user, sign_in, headers
):
    make_user()
    device_token = sign_in(platform="mobile")["device_token"]

    body = trusted_sign_in(client, device_token, "mobile", headers)

    assert body["status"] == "signed_in"
    assert session_for(db, body["access_token"]).platform == "web"


def test_sign_in_with_a_code_is_audited_with_the_platform(client, db, make_user, sign_in):
    user = make_user()

    sign_in(platform="mobile")

    assert sign_in_audit_details(db, user) == [{"two_factor": True, "platform": "mobile"}]


def test_trusted_sign_in_is_audited_with_the_platform(client, db, make_user, sign_in):
    user = make_user()
    device_token = sign_in()["device_token"]

    trusted_sign_in(client, device_token, "web")

    assert sign_in_audit_details(db, user)[-1] == {"two_factor": False, "platform": "web"}


@pytest.mark.parametrize("platform", ["desktop", "", None], ids=["unknown", "empty", "null"])
def test_sign_in_refuses_another_platform(client, make_user, platform):
    make_user()

    response = client.post(
        "/auth/signin",
        json={"email": "sarah@example.com", "password": PASSWORD, "platform": platform},
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "platform"


@pytest.mark.parametrize("platform", ["desktop", "", None], ids=["unknown", "empty", "null"])
def test_verify_refuses_another_platform(client, db, make_user, email_sender, platform):
    make_user()
    challenge = post_sign_in(client).json()

    response = client.post(
        "/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "code": last_code(email_sender),
            "platform": platform,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "platform"
    assert db.scalars(select(UserSession)).first() is None
