"""The "saving fails" alternate scenarios in stories 11.2 (Reset Password while signed in)
and 12.2 (Policy Updates)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.dml import Update

from app.accounts.models import PolicyVersion
from tests.helpers import PASSWORD, bearer


def failing_commit():
    raise OperationalError("COMMIT", None, ConnectionError("database is down"))


def test_password_change_that_cant_be_saved(client, db, make_user, sign_in, monkeypatch):
    make_user()
    token = sign_in()["access_token"]

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", failing_commit)
        response = client.post(
            "/me/password",
            headers=bearer(token),
            json={
                "current_password": PASSWORD,
                "new_password": "Renewal#2027",
                "confirm_password": "Renewal#2027",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "We couldn’t change your password just now. Please try again."
    )
    assert sign_in(password=PASSWORD)["status"] == "signed_in"  # nothing changed


def failing(*args, **kwargs):
    raise OperationalError("SELECT ... FOR UPDATE", None, ConnectionError("database is down"))


@pytest.mark.parametrize("fails_at", ["row-lock", "updates"])
def test_password_change_that_fails_before_the_commit(
    client, db, make_user, sign_in, monkeypatch, fails_at
):
    make_user()
    token = sign_in()["access_token"]
    other_device = sign_in()["access_token"]
    real_execute = db.execute

    def failing_updates(statement, *args, **kwargs):
        if isinstance(statement, Update):
            failing()
        return real_execute(statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        if fails_at == "row-lock":
            patch.setattr(db, "refresh", failing)
        else:
            patch.setattr(db, "execute", failing_updates)
        response = client.post(
            "/me/password",
            headers=bearer(token),
            json={
                "current_password": PASSWORD,
                "new_password": "Renewal#2027",
                "confirm_password": "Renewal#2027",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "save_failed",
        "message": "We couldn’t change your password just now. Please try again.",
        "field": None,
    }
    # Nothing changed: the other device is still signed in, and the old password still works.
    assert client.get("/me", headers=bearer(other_device)).status_code == 200
    assert sign_in(password=PASSWORD)["status"] == "signed_in"


def test_policy_acceptance_that_cant_be_saved(client, db, make_user, sign_in, monkeypatch):
    make_user()
    headers = bearer(sign_in()["access_token"])
    policy = PolicyVersion(
        kind="terms",
        version="2.0",
        title="Terms of Service",
        published_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(policy)
    db.commit()

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", failing_commit)
        response = client.post(
            "/me/policy-acceptances",
            headers=headers,
            json={"policy_version_ids": [str(policy.id)]},
        )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "We couldn’t save your acceptance just now. Please try again."
    )
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "policy_update"
