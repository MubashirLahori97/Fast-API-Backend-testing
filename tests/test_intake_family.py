"""Story 2.2: Complete Guided Health Intake - Family Member."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.profiles.models import Profile
from tests.helpers import bearer

STEPS = [
    {"family_relationship": "child"},
    {"first_name": "azka"},
    {"date_of_birth": (datetime.now(UTC).date() - timedelta(days=365 * 9)).isoformat()},
    {"advocate_consent": "parent_or_guardian"},
    {"sex_at_birth": "female"},
    {"gender_identity": "woman"},
    {"pronouns": "she_her"},
]


@pytest.fixture
def headers(make_user, sign_in) -> dict[str, str]:
    """A subscribed client (Basic plan) who has finished their own intake."""
    make_user(subscription_plan="basic")
    return bearer(sign_in()["access_token"])


def start(client, headers) -> dict:
    return client.post("/profiles/family", headers=headers).json()


def answer(client, headers, profile_id, body):
    return client.patch(f"/profiles/{profile_id}/intake", headers=headers, json=body)


def add_member(client, headers, steps=STEPS) -> str:
    profile_id = start(client, headers)["profile_id"]
    for body in steps:
        answer(client, headers, profile_id, body)
    client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)
    return profile_id


def error(response) -> tuple[str, str]:
    body = response.json()["error"]
    return body["field"], body["message"]


def test_trial_client_is_asked_to_upgrade(client, make_user, sign_in):
    make_user()  # on the free trial
    headers = bearer(sign_in()["access_token"])

    response = client.post("/profiles/family", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "family_plan_required",
        "message": "Adding family members is part of the family plan. Upgrade to add them.",
        "field": None,
    }


def test_adding_a_family_member_starts_with_the_relationship(client, headers):
    response = client.post("/profiles/family", headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["is_self"] is False
    assert body["next_question"] == "family_relationship"


def test_steps_come_in_the_story_order(client, headers):
    profile_id = start(client, headers)["profile_id"]

    questions = [
        answer(client, headers, profile_id, body).json()["next_question"] for body in STEPS
    ]

    assert questions == [
        "first_name",
        "date_of_birth",
        "advocate_consent",
        "sex_at_birth",
        "gender_identity",
        "pronouns",
        "done",
    ]


def test_first_name_gets_a_capital_letter(client, headers):
    profile_id = start(client, headers)["profile_id"]

    body = answer(client, headers, profile_id, {"first_name": "  azka "}).json()

    assert body["first_name"] == "Azka"


def test_empty_first_name(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, {"first_name": " "})

    assert response.status_code == 422
    assert error(response) == (
        "first_name",
        "What should I call them? Please enter their first name.",
    )


def test_family_members_under_13_can_be_added(client, headers):
    profile_id = start(client, headers)["profile_id"]
    four_years_old = (datetime.now(UTC).date() - timedelta(days=365 * 4)).isoformat()

    response = answer(client, headers, profile_id, {"date_of_birth": four_years_old})

    assert response.status_code == 200


def test_consent_is_needed_to_continue(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS[:3]:
        answer(client, headers, profile_id, body)

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 422
    assert error(response) == (
        "advocate_consent",
        "Please let me know how you’re able to look after Azka’s health.",
    )


def test_consent_is_recorded_with_its_time_but_not_its_option(client, db, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS[:4]:
        answer(client, headers, profile_id, body)

    profile = db.get(Profile, uuid.UUID(profile_id))
    db.refresh(profile)
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "profile.advocate_consent_recorded")
    ).one()
    assert profile.advocate_consent == "parent_or_guardian"
    assert profile.advocate_consent_at is not None
    assert event.target_id == profile_id
    assert event.details == {}


def test_only_one_consent_option(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, {"advocate_consent": ["agreed", "parent"]})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        (
            {"gender_identity": "other"},
            "gender_identity_other",
            "Tell me in your own words how Azka identifies.",
        ),
        (
            {"pronouns": "other", "pronouns_other": "  "},
            "pronouns_other",
            "Tell me which pronouns you’d like me to use for Azka.",
        ),
    ],
    ids=["gender", "pronouns"],
)
def test_other_needs_a_write_in_naming_the_member(client, headers, body, field, message):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, {"first_name": "azka"})

    response = answer(client, headers, profile_id, body)

    assert response.status_code == 422
    assert error(response) == (field, message)


def test_completing_greets_the_client_for_the_member(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS:
        answer(client, headers, profile_id, body)

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "profile_id": profile_id,
        "message": "Thank you, Sarah. I’m glad you’re here for Azka. "
        "Tell me what’s been going on, and I’ll ask what I need as we go.",
    }


def test_new_member_appears_in_the_profiles_list(client, headers):
    profile_id = add_member(client, headers)

    profiles = client.get("/profiles", headers=headers).json()

    assert [(p["first_name"], p["relationship"], p["is_self"]) for p in profiles] == [
        ("Sarah", None, True),
        ("Azka", "child", False),
    ]
    assert profiles[1]["id"] == profile_id
    assert profiles[1]["age"] in (8, 9)


def test_plan_limit_is_enforced(client, headers):
    for _ in range(3):
        add_member(client, headers)

    response = client.post("/profiles/family", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "You’ve added all the family members included in your plan. Add another member to continue."
    )


def test_leaving_part_way_resumes_the_same_draft(client, headers):
    first = start(client, headers)
    answer(client, headers, first["profile_id"], STEPS[0])

    again = client.post("/profiles/family", headers=headers)

    assert again.status_code == 200
    assert again.json()["profile_id"] == first["profile_id"]
    assert again.json()["next_question"] == "first_name"


def test_cancelling_leaves_no_profile(client, db, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, STEPS[0])

    response = client.delete(f"/profiles/{profile_id}", headers=headers)

    assert response.status_code == 204
    assert db.get(Profile, uuid.UUID(profile_id)) is None
    assert [p["is_self"] for p in client.get("/profiles", headers=headers).json()] == [True]


def test_a_finished_profile_cannot_be_cancelled(client, headers):
    profile_id = add_member(client, headers)

    assert client.delete(f"/profiles/{profile_id}", headers=headers).status_code == 409


def test_family_questions_are_refused_on_the_clients_own_profile(client, make_user, sign_in):
    make_user(intake_done=False, subscription_plan="basic")
    headers = bearer(sign_in()["access_token"])
    profile_id = client.post("/profiles/self", headers=headers).json()["profile_id"]

    response = answer(client, headers, profile_id, {"advocate_consent": "agreed"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "advocate_consent"


def test_another_clients_family_draft_is_not_found(client, make_user, sign_in, headers):
    profile_id = start(client, headers)["profile_id"]
    make_user(email="maria@example.com", subscription_plan="basic")
    marias_headers = bearer(sign_in(email="maria@example.com")["access_token"])

    assert client.delete(f"/profiles/{profile_id}", headers=marias_headers).status_code == 404
    assert answer(client, marias_headers, profile_id, STEPS[0]).status_code == 404


def test_plan_change_is_checked_again_at_completion(client, db, make_user, sign_in):
    user = make_user(subscription_plan="basic")
    headers = bearer(sign_in()["access_token"])
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS:
        answer(client, headers, profile_id, body)
    user.subscription_plan = None  # the subscription ended mid-way
    db.commit()

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "Adding family members is part of the family plan. Upgrade to add Azka."
    )


class TestFirstIntakeChoice:
    """Story 2.1 step 1: "For myself" or "For a family member", which Back can change."""

    @pytest.fixture
    def new_client(self, make_user, sign_in) -> dict[str, str]:
        make_user(intake_done=False, subscription_plan="basic")
        return bearer(sign_in()["access_token"])

    def test_switching_to_a_family_member_drops_the_self_draft(self, client, new_client):
        self_id = client.post("/profiles/self", headers=new_client).json()["profile_id"]
        answer(client, new_client, self_id, {"date_of_birth": "1990-03-14"})

        family_id = start(client, new_client)["profile_id"]

        assert [p["id"] for p in client.get("/profiles", headers=new_client).json()] == [family_id]
        assert client.get("/me/next-step", headers=new_client).json() == {
            "next_step": "intake",
            "profile_id": family_id,
        }

    def test_switching_back_to_myself_drops_the_family_draft(self, client, new_client):
        start(client, new_client)

        self_id = client.post("/profiles/self", headers=new_client).json()["profile_id"]

        assert [p["id"] for p in client.get("/profiles", headers=new_client).json()] == [self_id]

    def test_advocate_only_client_reaches_the_dashboard(self, client, new_client):
        add_member(client, new_client)

        assert client.get("/me/next-step", headers=new_client).json()["next_step"] == "dashboard"


def test_entitlements_show_the_plan(client, make_user, sign_in):
    make_user(subscription_plan="basic")
    headers = bearer(sign_in()["access_token"])
    add_member(client, headers)

    body = client.get("/me/entitlements", headers=headers).json()

    assert (body["plan"], body["family_members_included"], body["family_members_used"]) == (
        "basic",
        3,
        1,
    )


def test_trial_entitlements_have_no_family_places(client, make_user, sign_in):
    make_user()
    headers = bearer(sign_in()["access_token"])

    body = client.get("/me/entitlements", headers=headers).json()

    assert (body["plan"], body["family_members_included"]) == ("trial", 0)


def test_subscribed_client_after_the_trial_goes_to_the_dashboard(client, db, make_user, sign_in):
    user = make_user(subscription_plan="basic")
    user.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    headers = bearer(sign_in()["access_token"])

    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "dashboard"


def test_audit_events_hold_no_family_details(client, db, headers):
    profile_id = add_member(client, headers)

    events = db.scalars(select(AuditEvent).where(AuditEvent.target_id == profile_id)).all()

    flattened = str([event.details for event in events])
    for secret in (
        "azka",
        "Azka",
        "child",
        "female",
        "parent_or_guardian",
        str(date.today().year - 9),
    ):
        assert secret not in flattened


def test_going_back_to_change_the_name_asks_for_consent_again(client, db, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS[:4]:
        answer(client, headers, profile_id, body)

    body = answer(client, headers, profile_id, {"first_name": "maya"}).json()

    assert body["first_name"] == "Maya"
    assert body["advocate_consent"] is None
    assert body["next_question"] == "advocate_consent"
    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)
    assert response.json()["error"]["message"] == (
        "Please let me know how you’re able to look after Maya’s health."
    )
    cleared = select(AuditEvent).where(AuditEvent.action == "profile.advocate_consent_cleared")
    assert db.scalars(cleared).one().details == {}


def test_resending_the_same_name_keeps_the_consent(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in STEPS[:4]:
        answer(client, headers, profile_id, body)

    body = answer(client, headers, profile_id, {"first_name": "Azka"}).json()

    assert body["advocate_consent"] == "parent_or_guardian"


def test_completing_without_a_first_name(client, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, STEPS[0])

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 422
    assert error(response) == (
        "first_name",
        "What should I call them? Please enter their first name.",
    )


def test_a_draft_does_not_take_a_place(client, headers):
    add_member(client, headers)
    add_member(client, headers)
    start(client, headers)

    body = client.get("/me/entitlements", headers=headers).json()

    assert body["family_members_used"] == 2


def test_write_in_before_the_name_says_they(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, {"gender_identity": "other"})

    assert error(response) == (
        "gender_identity_other",
        "Tell me in your own words how they identify.",
    )


def test_unknown_plan_values_are_refused_by_the_database(db, make_user):
    from sqlalchemy.exc import IntegrityError

    user = make_user()
    user.subscription_plan = "family"

    with pytest.raises(IntegrityError):
        db.flush()
