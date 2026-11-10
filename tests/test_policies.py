"""Story 12.2: Policy Updates (client side), and the after-sign-in routing from story 1.2."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.accounts.models import PolicyVersion
from app.core.audit import AuditEvent
from tests.helpers import bearer


@pytest.fixture
def signed_in(make_user, sign_in):
    """(user, headers) for a client who accepted the policies at sign-up."""
    user = make_user()
    return user, bearer(sign_in()["access_token"])


def not_accepted(policy: PolicyVersion) -> dict:
    """The error detail for an updated policy whose checkbox wasn't ticked (story 12.2)."""
    return {
        "field": "policy_version_ids",
        "policy_version_id": str(policy.id),
        "message": (
            f"Please confirm you’ve read and accept the updated {policy.title} to continue."
        ),
    }


def publish_privacy(db) -> PolicyVersion:
    policy = PolicyVersion(
        kind="privacy",
        version="2.0",
        title="Privacy Policy",
        published_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(policy)
    db.commit()
    return policy


def publish_terms(db, version="2.0", published_at=None) -> PolicyVersion:
    policy = PolicyVersion(
        kind="terms",
        version=version,
        title="Terms of Service",
        published_at=published_at or datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(policy)
    db.commit()
    return policy


def test_current_policies_need_no_sign_in(client):
    response = client.get("/policies/current")

    assert response.status_code == 200
    assert {policy["title"] for policy in response.json()} == {
        "Terms of Service",
        "Privacy Policy",
    }


def test_up_to_date_client_goes_to_the_dashboard(client, signed_in):
    _, headers = signed_in

    assert client.get("/me/pending-consents", headers=headers).json() == []
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "dashboard"


def test_updated_policy_comes_first(client, db, signed_in):
    _, headers = signed_in
    policy = publish_terms(db)

    pending = client.get("/me/pending-consents", headers=headers).json()

    assert [item["id"] for item in pending] == [str(policy.id)]
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "policy_update"


def test_continuing_without_accepting_is_refused(client, db, signed_in):
    _, headers = signed_in
    terms = publish_terms(db)

    response = client.post("/me/policy-acceptances", headers=headers, json={})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "policy_not_accepted",
        "message": (
            "Please confirm you’ve read and accept the updated Terms of Service to continue."
        ),
        "field": "policy_version_ids",
        "details": [not_accepted(terms)],
    }


def test_each_unticked_policy_gets_its_own_message(client, db, signed_in):
    _, headers = signed_in
    terms = publish_terms(db)
    privacy = publish_privacy(db)

    response = client.post("/me/policy-acceptances", headers=headers, json={})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"] == [not_accepted(privacy), not_accepted(terms)]
    assert error["message"] == error["details"][0]["message"]


def test_accepting_records_the_version(client, db, signed_in):
    user, headers = signed_in
    policy = publish_terms(db)

    response = client.post(
        "/me/policy-acceptances", headers=headers, json={"policy_version_ids": [str(policy.id)]}
    )

    assert response.json() == {"message": "Thanks, you’re all set."}
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "dashboard"
    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_id == user.id, AuditEvent.target_id == str(policy.id)
        )
    ).one()
    assert event.details == {"kind": "terms", "version": "2.0"}


def test_version_published_in_the_future_isnt_current_yet(client, db, signed_in):
    _, headers = signed_in
    publish_terms(db, published_at=datetime.now(UTC) + timedelta(days=1))

    assert client.get("/me/pending-consents", headers=headers).json() == []


def test_trial_ended_goes_to_the_upgrade_screen(client, db, signed_in):
    user, headers = signed_in
    user.trial_ends_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "upgrade"


def test_next_step_needs_a_signed_in_client(client):
    assert client.get("/me/next-step").status_code == 401


def test_several_updated_policies_must_all_be_accepted(client, db, signed_in):
    _, headers = signed_in
    terms = publish_terms(db)
    privacy = publish_privacy(db)

    partial = client.post(
        "/me/policy-acceptances", headers=headers, json={"policy_version_ids": [str(terms.id)]}
    )
    both = client.post(
        "/me/policy-acceptances",
        headers=headers,
        json={"policy_version_ids": [str(terms.id), str(privacy.id)]},
    )

    assert partial.status_code == 422
    assert partial.json()["error"]["details"] == [not_accepted(privacy)]
    assert both.status_code == 200


def test_accepting_needs_a_signed_in_client(client):
    assert client.post("/me/policy-acceptances", json={}).status_code == 401
