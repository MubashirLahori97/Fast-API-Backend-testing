"""Story 1.4: Sign out, and the session rules every signed-in request follows (story 1.2's
Session Management: web and mobile sessions last differently)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth import dependencies as auth_dependencies
from app.auth.models import TrustedDevice, UserSession
from app.auth.security import hash_secret
from app.core.audit import AuditEvent
from tests.helpers import PASSWORD, bearer

SESSION_EXPIRED = {
    "code": "session_expired",
    "message": "Your session has expired. Please sign in again.",
    "field": None,
}
SIGNED_OUT_INACTIVE = {
    "code": "signed_out_inactive",
    "message": "You’ve been signed out after a period of inactivity. Please sign in again.",
    "field": None,
}
SIGNED_OUT = {
    "code": "signed_out",
    "message": "You’ve been signed out. Please sign in again to continue.",
    "field": None,
}
DEACTIVATED = {
    "code": "account_deactivated",
    "message": "Your account has been deactivated. Please contact the support team for help.",
    "field": None,
}


def session_for(db, token: str) -> UserSession:
    return db.scalar(select(UserSession).where(UserSession.token_hash == hash_secret(token)))


def device_for(db, device_token: str) -> TrustedDevice:
    return db.scalar(
        select(TrustedDevice).where(TrustedDevice.token_hash == hash_secret(device_token))
    )


def timed_out_reasons(db, user) -> list:
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_id == user.id, AuditEvent.action == "auth.session_timed_out"
        )
    )
    return [event.details for event in events]


def is_about(moment, expected) -> bool:
    return abs(moment - expected) < timedelta(minutes=1)


def travel(monkeypatch, ahead: timedelta) -> datetime:
    """Moves "now" forward for the session checks on signed-in requests."""
    moment = datetime.now(UTC) + ahead

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(auth_dependencies, "datetime", Later)
    return moment


def test_sign_out_ends_the_session(client, make_user, sign_in):
    make_user()
    token = sign_in()["access_token"]

    response = client.post("/auth/signout", headers=bearer(token))

    assert response.status_code == 204
    after = client.get("/me", headers=bearer(token))
    assert after.status_code == 401
    assert after.json()["error"] == SIGNED_OUT


def test_sign_out_forgets_the_device(client, make_user, sign_in):
    make_user()
    body = sign_in()
    client.post("/auth/signout", headers=bearer(body["access_token"]))

    again = client.post(
        "/auth/signin",
        json={
            "email": "sarah@example.com",
            "password": PASSWORD,
            "device_token": body["device_token"],
        },
    ).json()

    assert again["status"] == "verification_required"


def test_signing_out_one_device_keeps_the_others_signed_in(client, make_user, sign_in):
    make_user()
    phone = sign_in()["access_token"]
    laptop = sign_in()["access_token"]

    client.post("/auth/signout", headers=bearer(phone))

    assert client.get("/me", headers=bearer(laptop)).status_code == 200


def test_web_session_lasts_12_hours(client, db, make_user, sign_in):
    make_user()

    token = sign_in()["access_token"]

    expected = datetime.now(UTC) + timedelta(hours=12)
    assert is_about(session_for(db, token).expires_at, expected)


def test_inactive_web_session_is_signed_out(client, db, make_user, sign_in):
    user = make_user()
    token = sign_in()["access_token"]
    session_for(db, token).last_seen_at = datetime.now(UTC) - timedelta(minutes=31)
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"] == SIGNED_OUT_INACTIVE
    assert timed_out_reasons(db, user) == [{"reason": "signed_out_inactive"}]


def test_web_session_used_within_30_minutes_stays_signed_in(client, db, make_user, sign_in):
    make_user()
    token = sign_in()["access_token"]
    session_for(db, token).last_seen_at = datetime.now(UTC) - timedelta(minutes=29)
    db.commit()

    assert client.get("/me", headers=bearer(token)).status_code == 200


def test_mobile_session_lasts_30_days(client, db, make_user, sign_in):
    make_user()

    token = sign_in(platform="mobile")["access_token"]

    expected = datetime.now(UTC) + timedelta(days=30)
    assert is_about(session_for(db, token).expires_at, expected)


def test_mobile_session_ends_no_later_than_its_trusted_device(client, db, make_user, sign_in):
    make_user()
    device_token = sign_in(platform="mobile")["device_token"]
    device = device_for(db, device_token)
    device.expires_at = datetime.now(UTC) + timedelta(days=2)
    db.commit()

    body = sign_in(device_token=device_token, platform="mobile")

    assert body["status"] == "signed_in"  # no code: the device is still trusted
    assert session_for(db, body["access_token"]).expires_at == device.expires_at


def test_idle_mobile_session_stays_signed_in(client, db, make_user, sign_in):
    make_user()
    token = sign_in(platform="mobile")["access_token"]
    session_for(db, token).last_seen_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()

    assert client.get("/me", headers=bearer(token)).status_code == 200


def test_web_session_in_use_ends_12_hours_after_sign_in(
    client, db, make_user, sign_in, monkeypatch
):
    make_user()
    token = sign_in()["access_token"]
    moment = travel(monkeypatch, timedelta(hours=12, minutes=1))
    session_for(db, token).last_seen_at = moment - timedelta(minutes=1)  # still active
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"] == SESSION_EXPIRED


def test_web_session_in_use_works_until_12_hours(client, db, make_user, sign_in, monkeypatch):
    make_user()
    token = sign_in()["access_token"]
    moment = travel(monkeypatch, timedelta(hours=11, minutes=58))
    session_for(db, token).last_seen_at = moment - timedelta(minutes=1)
    db.commit()

    assert client.get("/me", headers=bearer(token)).status_code == 200


def test_mobile_session_ends_when_its_device_stops_being_trusted(
    client, db, make_user, sign_in, monkeypatch
):
    make_user()
    device_token = sign_in(platform="mobile")["device_token"]
    device_for(db, device_token).expires_at = datetime.now(UTC) + timedelta(days=2)
    db.commit()
    token = sign_in(device_token=device_token, platform="mobile")["access_token"]
    moment = travel(monkeypatch, timedelta(days=2, minutes=1))
    session_for(db, token).last_seen_at = moment - timedelta(minutes=1)
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"] == SESSION_EXPIRED


def test_mobile_session_has_no_idle_timeout(client, db, make_user, sign_in, monkeypatch):
    make_user()
    token = sign_in(platform="mobile")["access_token"]
    travel(monkeypatch, timedelta(days=29))  # untouched since sign-in

    assert client.get("/me", headers=bearer(token)).status_code == 200


@pytest.mark.parametrize("platform", [None, "mobile"], ids=["web", "mobile"])
def test_session_ends_after_its_maximum_age(client, db, make_user, sign_in, platform):
    user = make_user()
    token = sign_in(platform=platform)["access_token"]
    session_for(db, token).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"] == SESSION_EXPIRED
    assert timed_out_reasons(db, user) == [{"reason": "session_expired"}]


@pytest.mark.parametrize(
    ("ended_by", "status", "error"),
    [
        ("inactivity", 401, SIGNED_OUT_INACTIVE),
        ("maximum_age", 401, SESSION_EXPIRED),
        ("deactivation", 403, DEACTIVATED),
    ],
)
def test_ended_session_keeps_its_message(client, db, make_user, sign_in, ended_by, status, error):
    user = make_user()
    token = sign_in()["access_token"]
    session = session_for(db, token)
    if ended_by == "inactivity":
        session.last_seen_at = datetime.now(UTC) - timedelta(minutes=31)
    elif ended_by == "maximum_age":
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        user.status = "deactivated"
    db.commit()
    first = client.get("/me", headers=bearer(token))

    again = client.get("/me", headers=bearer(token))

    assert (first.status_code, first.json()["error"]) == (status, error)
    assert (again.status_code, again.json()["error"]) == (status, error)


def test_reactivated_account_gets_the_signed_out_message(client, db, make_user, sign_in):
    user = make_user()
    token = sign_in()["access_token"]
    user.status = "deactivated"
    db.commit()
    assert client.get("/me", headers=bearer(token)).status_code == 403
    user.status = "active"
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"] == SIGNED_OUT
    assert session_for(db, token).revoked_at is not None  # the session stays ended


def test_requests_without_a_token_must_sign_in(client):
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Please sign in to continue."


def test_unknown_token_must_sign_in(client):
    assert client.get("/me", headers=bearer("made-up")).json()["error"]["code"] == "not_signed_in"


def test_deactivated_client_loses_their_session(client, db, make_user, sign_in):
    user = make_user()
    token = sign_in()["access_token"]
    user.status = "deactivated"
    db.commit()

    response = client.get("/me", headers=bearer(token))

    assert response.status_code == 403
    assert response.json()["error"] == DEACTIVATED
    assert session_for(db, token).revoked_at is not None


def test_sign_out_is_audited(client, db, make_user, sign_in):
    user = make_user()
    client.post("/auth/signout", headers=bearer(sign_in()["access_token"]))

    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id))
    assert "auth.signed_out" in list(actions)


@pytest.mark.parametrize("access_token", [None, "made-up"], ids=["no-token", "unknown-token"])
def test_sign_out_with_only_the_device_token_is_audited(
    client, db, make_user, sign_in, access_token
):
    user = make_user()
    device_token = sign_in()["device_token"]

    response = client.post(
        "/auth/signout",
        headers=bearer(access_token) if access_token else {},
        json={"device_token": device_token},
    )

    assert response.status_code == 204
    actors = db.scalars(
        select(AuditEvent.actor_id).where(AuditEvent.action == "auth.signed_out")
    ).all()
    assert actors == [user.id]


def test_sign_out_ignores_another_accounts_device_token(client, db, make_user, sign_in):
    make_user(email="sarah@example.com")
    make_user(email="maria@example.com")
    sarahs_token = sign_in(email="sarah@example.com")["access_token"]
    maria = sign_in(email="maria@example.com")

    response = client.post(
        "/auth/signout",
        headers=bearer(sarahs_token),
        json={"device_token": maria["device_token"]},
    )

    assert response.status_code == 204
    assert device_for(db, maria["device_token"]) is not None
    assert client.get("/me", headers=bearer(maria["access_token"])).status_code == 200
    assert client.get("/me", headers=bearer(sarahs_token)).status_code == 401


def test_only_a_real_sign_out_is_audited(client, db, make_user, sign_in):
    make_user()
    token = sign_in()["access_token"]
    client.post("/auth/signout", headers=bearer(token))

    again = client.post("/auth/signout", headers=bearer(token))  # already signed out
    nothing = client.post("/auth/signout")

    assert again.status_code == nothing.status_code == 204
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.signed_out")).all()
    assert len(events) == 1


def test_sign_out_after_a_timeout_still_forgets_the_device(client, db, make_user, sign_in):
    make_user()
    body = sign_in()
    session_for(db, body["access_token"]).last_seen_at = datetime.now(UTC) - timedelta(minutes=31)
    db.commit()
    client.get("/me", headers=bearer(body["access_token"]))  # times out

    response = client.post(
        "/auth/signout",
        headers=bearer(body["access_token"]),
        json={"device_token": body["device_token"]},
    )

    assert response.status_code == 204
    again = client.post(
        "/auth/signin",
        json={
            "email": "sarah@example.com",
            "password": PASSWORD,
            "device_token": body["device_token"],
        },
    ).json()
    assert again["status"] == "verification_required"


def test_sign_out_can_be_repeated(client, make_user, sign_in):
    make_user()
    token = sign_in()["access_token"]

    assert client.post("/auth/signout", headers=bearer(token)).status_code == 204
    assert client.post("/auth/signout", headers=bearer(token)).status_code == 204
    assert client.post("/auth/signout").status_code == 204
