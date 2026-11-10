"""Story 1.3: Forget Password."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.models import PasswordResetToken
from app.auth.security import hash_secret
from app.core.audit import AuditEvent
from app.core.config import settings
from tests.helpers import (
    PASSWORD,
    PASSWORD_RULES,
    PASSWORDS_DONT_MATCH,
    bearer,
    last_reset_token,
)

NEW_PASSWORD = "Renewal#2027"
LINK_EXPIRED = "This link has expired. Please request a new one."
SENT = {"message": "If an account exists for this email, we’ve sent a link to reset your password."}


def forgot(client, email="sarah@example.com"):
    return client.post("/auth/password/forgot", json={"email": email})


def reset(client, token, new_password=NEW_PASSWORD, confirm=None):
    return client.post(
        "/auth/password/reset",
        json={
            "token": token,
            "new_password": new_password,
            "confirm_password": new_password if confirm is None else confirm,
        },
    )


def token_row(db, token: str) -> PasswordResetToken:
    return db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_secret(token))
    )


def test_registered_email_gets_a_reset_link(client, make_user, email_sender):
    make_user()

    response = forgot(client)

    assert response.status_code == 202
    assert response.json() == SENT
    assert email_sender.sent[-1].to == "sarah@example.com"
    assert last_reset_token(email_sender)


def test_unregistered_email_gets_the_same_answer_and_no_email(client, email_sender):
    response = forgot(client, "nobody@example.com")

    assert response.status_code == 202
    assert response.json() == SENT
    assert email_sender.sent == []


def test_deactivated_account_gets_no_email(client, make_user, email_sender):
    make_user(status="deactivated")

    forgot(client)

    assert email_sender.sent == []


def test_asking_twice_quickly_sends_one_email(client, make_user, email_sender):
    make_user()

    forgot(client)
    forgot(client)

    assert len(email_sender.sent) == 1


@pytest.mark.parametrize(
    ("email", "message"),
    [("", "Email is required."), ("sarah@", "Please enter a valid email address.")],
    ids=["empty", "invalid"],
)
def test_forgot_password_validation(client, email, message):
    response = forgot(client, email)

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == ("email", message)


def test_reset_link_lasts_60_minutes(client, db, make_user, email_sender):
    make_user()
    forgot(client)

    row = token_row(db, last_reset_token(email_sender))

    expected = datetime.now(UTC) + timedelta(minutes=60)
    assert abs(row.expires_at - expected) < timedelta(minutes=1)
    assert "expires in 60 minutes" in email_sender.sent[-1].body


def test_reset_email_names_your_oracle(client, make_user, email_sender):
    make_user()
    forgot(client)

    body = email_sender.sent[-1].body
    assert "Your Oracle" in body
    assert "Clinician" not in body


def test_reset_changes_the_password(client, make_user, email_sender, sign_in):
    make_user()
    forgot(client)

    response = reset(client, last_reset_token(email_sender))

    assert response.status_code == 200
    assert response.json() == {"message": "Your password has been reset. Please sign in."}
    assert email_sender.sent[-1].subject == "Your password was changed"
    assert sign_in(password=PASSWORD).get("error", {}).get("code") == "invalid_credentials"
    assert sign_in(password=NEW_PASSWORD)["status"] == "signed_in"


def test_reset_signs_out_every_device_and_requires_2fa(client, make_user, sign_in, email_sender):
    make_user()
    body = sign_in()
    forgot(client)
    reset(client, last_reset_token(email_sender))

    after = client.get("/me", headers=bearer(body["access_token"]))
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "signed_out"
    again = client.post(
        "/auth/signin",
        json={
            "email": "sarah@example.com",
            "password": NEW_PASSWORD,
            "device_token": body["device_token"],
        },
    ).json()
    assert again["status"] == "verification_required"


def test_reset_unlocks_a_locked_account(client, make_user, email_sender, sign_in):
    make_user(locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_sign_ins=3)
    forgot(client)
    reset(client, last_reset_token(email_sender))

    assert sign_in(password=NEW_PASSWORD)["status"] == "signed_in"


def test_link_works_only_once(client, make_user, email_sender):
    make_user()
    forgot(client)
    token = last_reset_token(email_sender)
    reset(client, token)

    response = reset(client, token, new_password="Another#2028")

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "reset_link_invalid",
        "message": LINK_EXPIRED,
        "field": None,
    }


def test_expired_link(client, db, make_user, email_sender):
    make_user()
    forgot(client)
    token = last_reset_token(email_sender)
    token_row(db, token).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = reset(client, token)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "reset_link_expired",
        "message": LINK_EXPIRED,
        "field": None,
    }


def test_made_up_link(client):
    response = reset(client, "made-up")

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "reset_link_invalid",
        "message": LINK_EXPIRED,
        "field": None,
    }


def test_a_new_link_closes_the_old_one(client, db, make_user, email_sender):
    make_user()
    forgot(client)
    old_token = last_reset_token(email_sender)
    token_row(db, old_token).created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    forgot(client)

    assert reset(client, old_token).json()["error"]["code"] == "reset_link_invalid"
    assert reset(client, last_reset_token(email_sender)).status_code == 200


def test_new_password_cannot_be_the_current_one(client, make_user, email_sender):
    make_user()
    forgot(client)

    response = reset(client, last_reset_token(email_sender), new_password=PASSWORD)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "password_reused",
        "message": "Please choose a password you haven’t used before.",
        "field": "new_password",
    }


def test_reusing_the_current_password_is_audited(client, db, make_user, email_sender):
    user = make_user()
    forgot(client)

    reset(client, last_reset_token(email_sender), new_password=PASSWORD)

    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "auth.password_reset.failed")
    ).one()
    assert (event.actor_id, event.details) == (user.id, {"reason": "password_reused"})


def test_reusing_the_current_password_counts_towards_the_ip_limit(
    client, db, make_user, email_sender
):
    make_user()
    forgot(client)
    token = last_reset_token(email_sender)
    for _ in range(settings.ip_failure_limit - 1):
        db.add(AuditEvent(action="auth.password_reset.failed", ip_address="testclient"))
    db.commit()
    assert reset(client, token, new_password=PASSWORD).status_code == 400  # the 20th failure

    response = reset(client, token)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


@pytest.mark.parametrize(
    ("new_password", "confirm", "field", "message"),
    [
        ("", "", "new_password", "Please enter a new password."),
        ("weakpass", "weakpass", "new_password", PASSWORD_RULES),
        (NEW_PASSWORD, "", "confirm_password", PASSWORDS_DONT_MATCH),
        (NEW_PASSWORD, "Renewal#2028", "confirm_password", PASSWORDS_DONT_MATCH),
    ],
    ids=["new-empty", "weak", "confirm-empty", "mismatch"],
)
def test_reset_validation(client, make_user, email_sender, new_password, confirm, field, message):
    make_user()
    forgot(client)

    response = client.post(
        "/auth/password/reset",
        json={
            "token": last_reset_token(email_sender),
            "new_password": new_password,
            "confirm_password": confirm,
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)


def test_check_link_before_showing_the_form(client, db, make_user, email_sender):
    make_user()
    forgot(client)
    token = last_reset_token(email_sender)

    response = client.post("/auth/password/reset/check", json={"token": token})

    assert response.status_code == 200
    assert response.json() == {"message": "This reset link is valid."}


def test_reset_link_keeps_the_token_out_of_server_logs(client, make_user, email_sender):
    make_user()
    forgot(client)

    assert "#token=" in email_sender.sent[-1].body


@pytest.mark.parametrize(
    ("link", "code"),
    [
        ("expired", "reset_link_expired"),
        ("used", "reset_link_invalid"),
        ("made-up", "reset_link_invalid"),
    ],
)
def test_check_refuses_a_link_that_no_longer_works(client, db, make_user, email_sender, link, code):
    make_user()
    forgot(client)
    token = last_reset_token(email_sender)
    if link == "expired":
        token_row(db, token).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    elif link == "used":
        reset(client, token)
    else:
        token = "made-up"

    response = client.post("/auth/password/reset/check", json={"token": token})

    assert response.status_code == 400
    assert response.json()["error"] == {"code": code, "message": LINK_EXPIRED, "field": None}


def test_reset_is_audited(client, db, make_user, email_sender):
    user = make_user()
    forgot(client)
    reset(client, last_reset_token(email_sender))

    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id)))
    assert {"auth.password_reset.requested", "auth.password_reset.completed"} <= actions


# Tries with the current password on one link (R1 security review)


def link_made_a_while_ago(db, email_sender) -> str:
    """The latest reset link, dated two minutes back. Within a test Postgres's now() stays at
    the moment the test began, so the link and the audit events written later would otherwise
    carry the same timestamp, and the app counts only events after the link was made."""
    token = last_reset_token(email_sender)
    token_row(db, token).created_at = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()
    return token


def test_fifth_try_with_the_current_password_still_says_reused(client, db, make_user, email_sender):
    make_user()
    forgot(client)
    token = link_made_a_while_ago(db, email_sender)
    for _ in range(settings.reset_link_max_failures - 1):
        reset(client, token, new_password=PASSWORD)

    response = reset(client, token, new_password=PASSWORD)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_reused"


@pytest.mark.parametrize("endpoint", ["reset", "check"])
def test_link_closes_after_5_tries_with_the_current_password(
    client, db, make_user, email_sender, endpoint
):
    make_user()
    forgot(client)
    token = link_made_a_while_ago(db, email_sender)
    for _ in range(settings.reset_link_max_failures):
        reset(client, token, new_password=PASSWORD)

    if endpoint == "reset":
        response = reset(client, token)  # a new password, and still refused
    else:
        response = client.post("/auth/password/reset/check", json={"token": token})

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "reset_link_invalid",
        "message": LINK_EXPIRED,
        "field": None,
    }


def test_tries_from_before_the_link_was_made_dont_count(client, db, make_user, email_sender):
    user = make_user()
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    for _ in range(settings.reset_link_max_failures - 1):  # tries on an earlier link
        db.add(
            AuditEvent(
                action="auth.password_reset.failed",
                actor_id=user.id,
                occurred_at=earlier,
                details={"reason": "password_reused"},
            )
        )
    db.commit()
    forgot(client)
    token = link_made_a_while_ago(db, email_sender)
    reset(client, token, new_password=PASSWORD)

    response = client.post("/auth/password/reset/check", json={"token": token})

    assert response.status_code == 200
