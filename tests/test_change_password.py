"""Story 11.2: Reset Password while signed in (POST /me/password)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.service import LOCKED_UNTIL_RESET
from app.core.audit import AuditEvent
from app.core.config import settings
from tests.helpers import PASSWORD, PASSWORD_RULES, bearer, last_code

NEW_PASSWORD = "Renewal#2027"


def change(client, token, current=PASSWORD, new=NEW_PASSWORD, confirm=None):
    return client.post(
        "/me/password",
        headers=bearer(token),
        json={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_change_keeps_this_device_and_signs_out_the_others(client, make_user, sign_in):
    make_user()
    this_device = sign_in()["access_token"]
    other_device = sign_in()["access_token"]

    response = change(client, this_device)

    assert response.status_code == 200
    assert response.json() == {"message": "Your password has been changed."}
    assert client.get("/me", headers=bearer(this_device)).status_code == 200
    other = client.get("/me", headers=bearer(other_device))
    assert other.status_code == 401
    assert other.json()["error"] == {
        "code": "signed_out",
        "message": "You’ve been signed out. Please sign in again to continue.",
        "field": None,
    }


def test_change_emails_a_confirmation(client, make_user, sign_in, email_sender):
    make_user()
    change(client, sign_in()["access_token"])

    assert email_sender.sent[-1].subject == "Your password was changed"


def test_changed_email_names_your_oracle_and_the_support_team(
    client, make_user, sign_in, email_sender
):
    make_user()
    change(client, sign_in()["access_token"])

    body = email_sender.sent[-1].body
    assert "Your Oracle" in body
    assert "Clinician" not in body
    assert "contact the support team" in body


def test_new_password_works_and_this_device_stays_trusted(client, make_user, sign_in):
    make_user()
    body = sign_in()
    change(client, body["access_token"])

    again = client.post(
        "/auth/signin",
        json={
            "email": "sarah@example.com",
            "password": NEW_PASSWORD,
            "device_token": body["device_token"],
        },
    ).json()

    assert again["status"] == "signed_in"


def test_other_devices_need_2fa_again(client, make_user, sign_in):
    make_user()
    this_device = sign_in()
    other_device = sign_in()
    change(client, this_device["access_token"])

    again = client.post(
        "/auth/signin",
        json={
            "email": "sarah@example.com",
            "password": NEW_PASSWORD,
            "device_token": other_device["device_token"],
        },
    ).json()

    assert again["status"] == "verification_required"


def test_wrong_current_password(client, db, make_user, sign_in):
    user = make_user()

    response = change(client, sign_in()["access_token"], current="Wrong!2026")

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "current_password_wrong",
        "message": "Your current password isn’t right. Please try again.",
        "field": "current_password",
    }
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id))
    assert "auth.password_change.failed" in list(actions)


def test_new_password_same_as_current(client, make_user, sign_in):
    make_user()

    response = change(client, sign_in()["access_token"], new=PASSWORD)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "password_reused",
        "message": "Please choose a password you haven’t used before.",
        "field": "new_password",
    }


@pytest.mark.parametrize(
    ("new", "confirm", "field", "message"),
    [
        ("weakpass", "weakpass", "new_password", PASSWORD_RULES),
        (
            NEW_PASSWORD,
            "Renewal#2028",
            "confirm_password",
            "The passwords don’t match. Please try again.",
        ),
    ],
    ids=["weak", "mismatch"],
)
def test_change_password_validation(client, make_user, sign_in, new, confirm, field, message):
    make_user()

    response = change(client, sign_in()["access_token"], new=new, confirm=confirm)

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)


def test_change_needs_a_signed_in_client(client):
    response = client.post("/me/password", json={})

    assert response.status_code == 401


@pytest.mark.parametrize("field", ["current_password", "new_password", "confirm_password"])
def test_empty_field_is_required(client, make_user, sign_in, field):
    make_user()
    body = {
        "current_password": PASSWORD,
        "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
    }

    response = client.post(
        "/me/password", headers=bearer(sign_in()["access_token"]), json={**body, field: ""}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, "This field is required.")


def test_missing_fields_are_each_required(client, make_user, sign_in):
    make_user()

    response = client.post("/me/password", headers=bearer(sign_in()["access_token"]), json={})

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "current_password", "message": "This field is required."},
        {"field": "new_password", "message": "This field is required."},
        {"field": "confirm_password", "message": "This field is required."},
    ]


def test_change_is_audited(client, db, make_user, sign_in):
    user = make_user()
    change(client, sign_in()["access_token"])

    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id))
    assert "auth.password_changed" in list(actions)


def test_guessing_the_current_password_ends_the_session(client, make_user, sign_in):
    make_user()
    token = sign_in()["access_token"]
    for _ in range(2):
        assert change(client, token, current="Wrong!2026").status_code == 400

    response = change(client, token, current="Wrong!2026")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"
    after = client.get("/me", headers=bearer(token))
    assert (after.status_code, after.json()["error"]["code"]) == (401, "signed_out")


# A change ends a lock (story 11.2 with the R1 security review)


def test_change_ends_a_lock(client, db, make_user, sign_in):
    user = make_user()
    token = sign_in()["access_token"]  # still signed in here while locked out elsewhere
    user.locked_until = LOCKED_UNTIL_RESET
    user.failed_sign_ins = 2
    db.commit()

    response = change(client, token)

    assert response.status_code == 200
    db.refresh(user)
    assert (user.locked_until, user.failed_sign_ins) == (None, 0)
    again = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": NEW_PASSWORD}
    )
    assert again.json()["status"] == "verification_required"


def test_change_records_when_the_password_changed(client, db, make_user, sign_in):
    user = make_user()

    change(client, sign_in()["access_token"])

    db.refresh(user)
    assert abs(user.password_changed_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_wrong_codes_before_a_change_stop_counting(client, db, make_user, sign_in, email_sender):
    user = make_user()
    token = sign_in()["access_token"]
    earlier = datetime.now(UTC) - timedelta(minutes=1)
    for _ in range(settings.max_failed_codes_per_hour - 1):
        db.add(AuditEvent(action="auth.code.failed", actor_id=user.id, occurred_at=earlier))
    db.commit()
    change(client, token)
    challenge = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": NEW_PASSWORD}
    ).json()
    code = last_code(email_sender)

    response = client.post(
        "/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "code": f"{(int(code) + 1) % 1_000_000:06d}",
        },
    )

    assert response.status_code == 400  # without the change, this would be the 10th: a lock
    assert response.json()["error"]["code"] == "code_wrong"
