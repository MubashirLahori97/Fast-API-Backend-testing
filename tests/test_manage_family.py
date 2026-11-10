"""Story 9.2: Manage Family Profiles."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.accounts.models import DeletionRequest
from app.core.audit import AuditEvent
from app.core.config import settings
from app.profiles.models import Profile
from app.profiles.service import _add_business_days
from tests.helpers import bearer
from tests.test_intake_family import STEPS, add_member, error
from tests.test_policies import publish_terms

LAST_ACTIVE = (
    "Azka is the only active person on your account. "
    "To remove them, please delete your account instead."
)
DELETION_SENT = "Your request has been sent. Azka’s data will be deleted within 10 business days."
BEING_DELETED = {
    "code": "deletion_requested",
    "message": "Azka’s data is being deleted, so their profile can’t be changed.",
    "field": None,
}

# The 9.2 changes, as (method, path after /profiles/{id}, body).
CHANGES = {
    "edit": ("PATCH", "", {"pronouns": "they_them"}),
    "turn-off": ("POST", "/turn-off", None),
    "turn-on": ("POST", "/turn-on", None),
    "remove": ("POST", "/deletion-request", {"confirm_name": "Azka"}),
}
ACTIONS = {"view": ("GET", "", None), **CHANGES}


@pytest.fixture
def headers(make_user, sign_in) -> dict[str, str]:
    """A subscribed client (Basic plan) who has finished their own intake."""
    make_user(subscription_plan="basic")
    return bearer(sign_in()["access_token"])


@pytest.fixture
def advocate(make_user, sign_in) -> dict[str, str]:
    """A subscribed client with no profile of their own, who manages only family members."""
    make_user(intake_done=False, subscription_plan="basic")
    return bearer(sign_in()["access_token"])


def named(name: str) -> list[dict]:
    """STEPS for a family member with another first name."""
    return [{"first_name": name} if "first_name" in step else step for step in STEPS]


def act(client, headers, profile_id, action):
    method, path, body = ACTIONS[action]
    return client.request(method, f"/profiles/{profile_id}{path}", headers=headers, json=body)


def edit(client, headers, profile_id, body):
    return client.patch(f"/profiles/{profile_id}", headers=headers, json=body)


def turn_off(client, headers, profile_id):
    return client.post(f"/profiles/{profile_id}/turn-off", headers=headers)


def turn_on(client, headers, profile_id):
    return client.post(f"/profiles/{profile_id}/turn-on", headers=headers)


def remove(client, headers, profile_id, confirm_name="Azka"):
    return client.post(
        f"/profiles/{profile_id}/deletion-request",
        headers=headers,
        json={"confirm_name": confirm_name},
    )


def overview(client, headers) -> dict:
    return client.get("/profiles/family", headers=headers).json()


def panel_ids(client, headers) -> list[str]:
    return [profile["id"] for profile in client.get("/profiles", headers=headers).json()]


def own_profile_id(client, headers) -> str:
    return next(p["id"] for p in client.get("/profiles", headers=headers).json() if p["is_self"])


def events(db, action, profile_id) -> list[AuditEvent]:
    return db.scalars(
        select(AuditEvent).where(AuditEvent.action == action, AuditEvent.target_id == profile_id)
    ).all()


def deletion_requests(db, profile_id) -> list[DeletionRequest]:
    return db.scalars(
        select(DeletionRequest).where(DeletionRequest.profile_id == uuid.UUID(profile_id))
    ).all()


def space_out_created_at(db, profile_ids) -> None:
    """Every request in a test shares one database transaction, where now() doesn't move, so
    all profiles get the same created_at. This spaces them a minute apart, in the given order."""
    start = datetime.now(UTC) - timedelta(hours=1)
    for minutes, profile_id in enumerate(profile_ids):
        db.get(Profile, uuid.UUID(profile_id)).created_at = start + timedelta(minutes=minutes)
    db.commit()


def add_two_in_order(client, db, headers) -> tuple[str, str]:
    """Adds Azka, then Maya, with Azka first in the order added."""
    first = add_member(client, headers)
    second = add_member(client, headers, named("maya"))
    space_out_created_at(db, [first, second])
    return first, second


def save_gender_other(db, profile_id, write_in) -> None:
    """Saves gender "Other" with a write-in directly, so no edit event is recorded first."""
    profile = db.get(Profile, uuid.UUID(profile_id))
    profile.gender_identity = "other"
    profile.gender_identity_other = write_in
    db.commit()


# The Manage Family screen


def test_overview_shows_how_many_places_are_in_use(client, headers):
    add_member(client, headers)
    add_member(client, headers, named("maya"))
    omar = add_member(client, headers, named("omar"))
    turn_off(client, headers, omar)

    body = overview(client, headers)

    assert (body["family_members_used"], body["family_members_included"]) == (2, 3)
    assert {member["first_name"]: member["status"] for member in body["members"]} == {
        "Azka": "active",
        "Maya": "active",
        "Omar": "turned_off",
    }


def test_member_card_shows_name_relationship_and_age(client, headers):
    profile_id = add_member(client, headers)

    card = overview(client, headers)["members"][0]

    assert card.pop("age") in (8, 9)
    assert card == {
        "id": profile_id,
        "first_name": "Azka",
        "relationship": "child",
        "status": "active",
        "health_profile_completion": None,
    }


def test_overview_lists_members_in_the_order_added(client, db, headers):
    ids = [add_member(client, headers, named(name)) for name in ("azka", "maya", "omar")]
    space_out_created_at(db, ids)
    turn_off(client, headers, ids[0])

    members = overview(client, headers)["members"]

    assert [member["id"] for member in members] == ids


def test_overview_leaves_out_unfinished_drafts(client, headers):
    add_member(client, headers)
    client.post("/profiles/family", headers=headers)

    body = overview(client, headers)

    assert [member["first_name"] for member in body["members"]] == ["Azka"]
    assert body["family_members_used"] == 1


def test_manage_family_needs_the_updated_policies_accepted(client, db, headers):
    publish_terms(db)

    response = client.get("/profiles/family", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy_update_required"


def test_view_shows_the_members_details(client, headers):
    profile_id = add_member(client, headers)

    details = client.get(f"/profiles/{profile_id}", headers=headers).json()

    assert details.pop("age") in (8, 9)
    assert details == {
        "id": profile_id,
        "is_self": False,
        "first_name": "Azka",
        "family_relationship": "child",
        "date_of_birth": STEPS[2]["date_of_birth"],
        "sex_at_birth": "female",
        "gender_identity": "woman",
        "gender_identity_other": None,
        "pronouns": "she_her",
        "pronouns_other": None,
        "status": "active",
        "intake_completed": True,
    }


# Turning a profile off


def test_turning_off_a_member(client, db, headers):
    profile_id = add_member(client, headers)

    response = turn_off(client, headers, profile_id)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Azka’s profile is turned off."
    assert (body["member"]["id"], body["member"]["status"]) == (profile_id, "turned_off")
    assert len(events(db, "profile.turned_off", profile_id)) == 1


def test_turned_off_member_keeps_their_details(client, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    details = client.get(f"/profiles/{profile_id}", headers=headers).json()

    assert (details["first_name"], details["sex_at_birth"], details["status"]) == (
        "Azka",
        "female",
        "turned_off",
    )


def test_turning_off_frees_a_place(client, headers):
    first = add_member(client, headers)
    add_member(client, headers)
    add_member(client, headers)
    full = client.post("/profiles/family", headers=headers)

    turn_off(client, headers, first)
    response = client.post("/profiles/family", headers=headers)

    assert (full.status_code, full.json()["error"]["code"]) == (403, "family_limit_reached")
    assert response.status_code == 201


def test_turned_off_member_is_not_counted_in_the_entitlements(client, headers):
    first = add_member(client, headers)
    add_member(client, headers)

    turn_off(client, headers, first)

    assert client.get("/me/entitlements", headers=headers).json()["family_members_used"] == 1


def test_turned_off_member_is_hidden_from_the_profile_panel(client, headers):
    profile_id = add_member(client, headers)

    turn_off(client, headers, profile_id)

    assert panel_ids(client, headers) == [own_profile_id(client, headers)]


def test_turning_off_twice_records_one_event(client, db, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    again = turn_off(client, headers, profile_id)

    assert again.status_code == 200
    assert again.json()["message"] == "Azka’s profile is turned off."
    assert len(events(db, "profile.turned_off", profile_id)) == 1


def test_client_with_their_own_profile_can_turn_off_their_only_member(client, headers):
    profile_id = add_member(client, headers)

    assert turn_off(client, headers, profile_id).status_code == 200


# Turning a profile on


def test_turning_on_with_a_free_place(client, db, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    response = turn_on(client, headers, profile_id)

    assert response.status_code == 200
    assert response.json()["message"] == "Azka’s profile is turned on."
    assert response.json()["member"]["status"] == "active"
    assert len(events(db, "profile.turned_on", profile_id)) == 1


def test_turned_on_member_is_back_in_the_profile_panel(client, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    turn_on(client, headers, profile_id)

    assert profile_id in panel_ids(client, headers)


def test_turning_on_with_all_places_in_use_shows_the_upgrade_prompt(client, headers):
    azka = add_member(client, headers)
    turn_off(client, headers, azka)
    for name in ("maya", "omar", "lina"):
        add_member(client, headers, named(name))

    response = turn_on(client, headers, azka)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "family_limit_reached",
        "message": "You have 3 active family members, the most your plan includes. "
        "Upgrade to turn on Azka’s profile, or turn off another family member first.",
        "field": None,
    }


def test_upgrade_prompt_for_a_one_member_plan_is_singular(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "family_members_included", 1)
    azka = add_member(client, headers)
    turn_off(client, headers, azka)
    add_member(client, headers, named("maya"))

    response = turn_on(client, headers, azka)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "You have 1 active family member, the most your plan includes. "
        "Upgrade to turn on Azka’s profile, or turn off another family member first."
    )


def test_turning_on_during_the_trial_needs_the_family_plan(client, db, make_user, sign_in):
    user = make_user(subscription_plan="basic")
    headers = bearer(sign_in()["access_token"])
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)
    user.subscription_plan = None
    db.commit()

    response = turn_on(client, headers, profile_id)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "family_plan_required",
        "message": "Family members are part of the family plan. Upgrade to turn on Azka’s profile.",
        "field": None,
    }


def test_turning_on_twice_records_one_event(client, db, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)
    turn_on(client, headers, profile_id)

    again = turn_on(client, headers, profile_id)

    assert again.status_code == 200
    assert again.json()["message"] == "Azka’s profile is turned on."
    assert len(events(db, "profile.turned_on", profile_id)) == 1


# Advocate-only clients and the default profile


def test_advocate_only_client_cannot_turn_off_their_last_active_member(client, advocate):
    profile_id = add_member(client, advocate)

    response = turn_off(client, advocate, profile_id)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "last_active_profile",
        "message": LAST_ACTIVE,
        "field": None,
    }


def test_advocate_only_client_cannot_remove_their_last_active_member(client, advocate):
    profile_id = add_member(client, advocate)

    response = remove(client, advocate, profile_id)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "last_active_profile",
        "message": LAST_ACTIVE,
        "field": None,
    }


def test_advocate_only_client_can_turn_off_one_of_two_active_members(client, advocate):
    first = add_member(client, advocate)
    add_member(client, advocate, named("maya"))

    assert turn_off(client, advocate, first).status_code == 200


def test_turned_off_member_can_be_removed_while_one_other_is_active(client, advocate):
    first = add_member(client, advocate)
    add_member(client, advocate, named("maya"))
    turn_off(client, advocate, first)

    assert remove(client, advocate, first).status_code == 200


def test_member_being_deleted_does_not_count_as_someone_else_active(client, advocate):
    azka = add_member(client, advocate)
    maya = add_member(client, advocate, named("maya"))
    remove(client, advocate, maya, "Maya")

    response = turn_off(client, advocate, azka)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_active_profile"
    assert response.json()["error"]["message"] == LAST_ACTIVE


@pytest.mark.parametrize("action", ["turn-off", "turn-on", "remove"])
def test_results_name_the_clients_own_profile_as_the_default(client, headers, action):
    profile_id = add_member(client, headers)

    response = act(client, headers, profile_id, action)

    assert response.status_code == 200
    assert response.json()["default_profile_id"] == own_profile_id(client, headers)


def test_turning_off_names_an_advocates_next_member_as_the_default(client, db, advocate):
    first, second = add_two_in_order(client, db, advocate)

    response = turn_off(client, advocate, first)

    assert response.json()["default_profile_id"] == second


def test_turning_on_names_an_advocates_first_member_as_the_default(client, db, advocate):
    first, _ = add_two_in_order(client, db, advocate)
    turn_off(client, advocate, first)

    response = turn_on(client, advocate, first)

    assert response.json()["default_profile_id"] == first


def test_removing_names_an_advocates_next_member_as_the_default(client, db, advocate):
    first, second = add_two_in_order(client, db, advocate)

    response = remove(client, advocate, first)

    assert response.json()["default_profile_id"] == second


def test_dashboard_opens_on_the_clients_own_profile(client, headers):
    add_member(client, headers)

    assert client.get("/me/next-step", headers=headers).json() == {
        "next_step": "dashboard",
        "profile_id": own_profile_id(client, headers),
    }


def test_advocate_only_dashboard_skips_a_turned_off_member(client, db, advocate):
    first, second = add_two_in_order(client, db, advocate)
    turn_off(client, advocate, first)

    assert client.get("/me/next-step", headers=advocate).json() == {
        "next_step": "dashboard",
        "profile_id": second,
    }


def test_advocate_only_dashboard_skips_a_member_being_deleted(client, db, advocate):
    first, second = add_two_in_order(client, db, advocate)
    remove(client, advocate, first)

    assert client.get("/me/next-step", headers=advocate).json() == {
        "next_step": "dashboard",
        "profile_id": second,
    }


# View & edit


def test_editing_updates_name_relationship_gender_and_pronouns(client, headers):
    profile_id = add_member(client, headers)

    response = edit(
        client,
        headers,
        profile_id,
        {
            "first_name": "maya",
            "family_relationship": "someone_else",
            "advocate_consent": "authorised_to_act",
            "gender_identity": "non_binary",
            "pronouns": "they_them",
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Thanks, I’ve updated Maya’s details."
    details = client.get(f"/profiles/{profile_id}", headers=headers).json()
    assert (
        details["first_name"],
        details["family_relationship"],
        details["gender_identity"],
        details["pronouns"],
    ) == ("Maya", "someone_else", "non_binary", "they_them")


def test_first_name_edit_keeps_the_advocate_consent(client, headers):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"first_name": "maya"})

    assert response.status_code == 200
    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()
    assert intake["advocate_consent"] == "parent_or_guardian"


def test_changing_the_relationship_needs_the_consent_again(client, headers):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"family_relationship": "partner"})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "consent_required",
        "message": "Please let me know how you’re able to look after Azka’s health.",
        "field": "advocate_consent",
    }


def test_new_relationship_is_saved_with_the_new_consent(client, headers):
    profile_id = add_member(client, headers)

    response = edit(
        client,
        headers,
        profile_id,
        {"family_relationship": "partner", "advocate_consent": "agreed"},
    )

    assert response.status_code == 200
    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()
    assert (intake["family_relationship"], intake["advocate_consent"]) == ("partner", "agreed")


def test_new_consent_is_recorded_with_its_time(client, db, headers):
    profile_id = add_member(client, headers)
    profile = db.get(Profile, uuid.UUID(profile_id))
    consented_at = profile.advocate_consent_at

    edit(
        client,
        headers,
        profile_id,
        {"family_relationship": "partner", "advocate_consent": "agreed"},
    )

    assert profile.advocate_consent_at > consented_at
    recorded = events(db, "profile.advocate_consent_recorded", profile_id)
    assert [event.details for event in recorded] == [{}, {}]  # the intake's, then the edit's
    [updated] = events(db, "profile.updated", profile_id)
    assert sorted(updated.details["fields"]) == ["advocate_consent", "family_relationship"]


def test_resending_the_same_consent_records_nothing(client, db, headers):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"advocate_consent": "parent_or_guardian"})

    assert response.status_code == 200
    assert len(events(db, "profile.advocate_consent_recorded", profile_id)) == 1  # the intake's
    assert events(db, "profile.updated", profile_id) == []


@pytest.mark.parametrize("first_name", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_first_name_cannot_be_emptied(client, headers, first_name):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"first_name": first_name})

    assert response.status_code == 422
    assert error(response) == ("first_name", "Please enter their first name.")


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
def test_other_needs_a_write_in(client, headers, body, field, message):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, body)

    assert response.status_code == 422
    assert error(response) == (field, message)


def test_other_with_a_write_in_is_saved(client, headers):
    profile_id = add_member(client, headers)

    response = edit(
        client,
        headers,
        profile_id,
        {
            "gender_identity": "other",
            "gender_identity_other": "Two-spirit",
            "pronouns": "other",
            "pronouns_other": "xe/xem",
        },
    )

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert (profile["gender_identity_other"], profile["pronouns_other"]) == ("Two-spirit", "xe/xem")


def test_write_in_can_be_changed_on_its_own(client, db, headers):
    profile_id = add_member(client, headers)
    save_gender_other(db, profile_id, "Genderqueer")

    response = edit(client, headers, profile_id, {"gender_identity_other": "Two-spirit"})

    assert response.status_code == 200
    assert response.json()["profile"]["gender_identity_other"] == "Two-spirit"


def test_write_in_cannot_be_emptied_on_its_own(client, db, headers):
    profile_id = add_member(client, headers)
    save_gender_other(db, profile_id, "Two-spirit")

    response = edit(client, headers, profile_id, {"gender_identity_other": ""})

    assert response.status_code == 422
    assert error(response) == (
        "gender_identity_other",
        "Tell me in your own words how Azka identifies.",
    )


def test_write_in_without_other_changes_nothing(client, db, headers):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"gender_identity_other": "Two-spirit"})

    assert response.status_code == 200
    assert response.json()["profile"]["gender_identity_other"] is None
    assert events(db, "profile.updated", profile_id) == []


def test_resending_other_keeps_the_saved_write_in(client, db, headers):
    profile_id = add_member(client, headers)
    save_gender_other(db, profile_id, "Two-spirit")

    response = edit(client, headers, profile_id, {"gender_identity": "other"})

    assert response.status_code == 200
    assert response.json()["profile"]["gender_identity_other"] == "Two-spirit"


def test_write_in_is_audited_as_its_choice(client, db, headers):
    profile_id = add_member(client, headers)
    save_gender_other(db, profile_id, "Genderqueer")

    edit(client, headers, profile_id, {"gender_identity_other": "Two-spirit"})

    [event] = events(db, "profile.updated", profile_id)
    assert event.details == {"fields": ["gender_identity"]}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"date_of_birth": "2015-01-01"}, "date_of_birth"),
        ({"sex_at_birth": "male"}, "sex_at_birth"),
    ],
    ids=["date_of_birth", "sex_at_birth"],
)
def test_date_of_birth_and_sex_at_birth_are_read_only(client, headers, body, field):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, body)

    assert response.status_code == 422
    assert error(response) == (
        field,
        "Azka’s date of birth and sex assigned at birth can’t be changed here. "
        "If something is wrong, please contact The Oracle’s team.",
    )


def test_unchanged_read_only_fields_are_accepted_with_an_edit(client, headers):
    profile_id = add_member(client, headers)

    response = edit(
        client,
        headers,
        profile_id,
        {
            "first_name": "maya",
            "date_of_birth": STEPS[2]["date_of_birth"],
            "sex_at_birth": "female",
        },
    )

    assert response.status_code == 200
    assert response.json()["profile"]["first_name"] == "Maya"


def test_edit_audit_lists_only_the_changed_fields(client, db, headers):
    profile_id = add_member(client, headers)

    edit(
        client,
        headers,
        profile_id,
        {"first_name": "maya", "family_relationship": "child", "pronouns": "they_them"},
    )

    [event] = events(db, "profile.updated", profile_id)
    assert list(event.details) == ["fields"]
    assert sorted(event.details["fields"]) == ["first_name", "pronouns"]


def test_edit_that_changes_nothing_records_no_event(client, db, headers):
    profile_id = add_member(client, headers)

    response = edit(client, headers, profile_id, {"first_name": "Azka", "gender_identity": "woman"})

    assert response.status_code == 200
    assert events(db, "profile.updated", profile_id) == []


def test_turned_off_member_can_still_be_edited(client, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    response = edit(client, headers, profile_id, {"first_name": "maya"})

    assert response.status_code == 200
    assert (response.json()["profile"]["first_name"], response.json()["profile"]["status"]) == (
        "Maya",
        "turned_off",
    )


# Removing a family member


def test_removing_sends_a_deletion_request(client, headers):
    profile_id = add_member(client, headers)

    response = remove(client, headers, profile_id)

    assert response.status_code == 200
    assert response.json()["message"] == DELETION_SENT
    assert response.json()["member"]["status"] == "deletion_requested"


def test_deletion_request_is_recorded_for_the_team(client, db, make_user, sign_in):
    user = make_user(subscription_plan="basic")
    headers = bearer(sign_in()["access_token"])
    profile_id = add_member(client, headers)

    remove(client, headers, profile_id)

    [request] = deletion_requests(db, profile_id)
    assert (request.account_id, request.kind, request.status) == (
        user.id,
        "family_member",
        "pending",
    )
    assert request.due_at == _add_business_days(request.requested_at, 10)


def test_deletion_request_audit_event_points_to_the_request(client, db, headers):
    profile_id = add_member(client, headers)

    remove(client, headers, profile_id)

    [request] = deletion_requests(db, profile_id)
    [event] = events(db, "profile.deletion_requested", profile_id)
    assert event.details == {"deletion_request_id": str(request.id)}


@pytest.mark.parametrize(
    "body",
    [{"confirm_name": "Maya"}, {}, {"confirm_name": None}],
    ids=["wrong", "missing", "null"],
)
def test_removing_needs_the_first_name_typed(client, headers, body):
    profile_id = add_member(client, headers)

    response = client.post(f"/profiles/{profile_id}/deletion-request", headers=headers, json=body)

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "name_mismatch",
        "message": "Please type Azka’s first name to confirm.",
        "field": "confirm_name",
    }


def test_typed_name_ignores_case_and_spaces(client, headers):
    profile_id = add_member(client, headers)

    assert remove(client, headers, profile_id, " azka ").status_code == 200


def test_member_being_deleted_keeps_their_place_until_it_is_done(client, headers):
    profile_id = add_member(client, headers)

    remove(client, headers, profile_id)

    body = overview(client, headers)
    assert body["family_members_used"] == 1
    assert [member["status"] for member in body["members"]] == ["deletion_requested"]


def test_turning_off_then_removing_frees_the_place(client, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    remove(client, headers, profile_id)

    assert overview(client, headers)["family_members_used"] == 0


def test_member_being_deleted_stays_in_the_profile_panel(client, headers):
    profile_id = add_member(client, headers)

    remove(client, headers, profile_id)

    panel = client.get("/profiles", headers=headers).json()
    assert [(profile["id"], profile["status"]) for profile in panel] == [
        (own_profile_id(client, headers), "active"),
        (profile_id, "deletion_requested"),
    ]


def test_repeating_the_deletion_request_records_one_request(client, db, headers):
    profile_id = add_member(client, headers)
    remove(client, headers, profile_id)

    again = remove(client, headers, profile_id)

    assert again.status_code == 200
    assert again.json()["message"] == DELETION_SENT
    assert len(deletion_requests(db, profile_id)) == 1
    assert len(events(db, "profile.deletion_requested", profile_id)) == 1


@pytest.mark.parametrize("action", ["edit", "turn-on", "turn-off"])
def test_member_being_deleted_cannot_be_changed(client, headers, action):
    profile_id = add_member(client, headers)
    remove(client, headers, profile_id)

    response = act(client, headers, profile_id, action)

    assert response.status_code == 409
    assert response.json()["error"] == BEING_DELETED


@pytest.mark.parametrize(
    ("start", "days", "due"),
    [
        (datetime(2026, 10, 30, 9, tzinfo=UTC), 10, datetime(2026, 11, 13, 9, tzinfo=UTC)),
        (datetime(2026, 10, 28, 9, tzinfo=UTC), 1, datetime(2026, 10, 29, 9, tzinfo=UTC)),
        (datetime(2026, 10, 30, 9, tzinfo=UTC), 1, datetime(2026, 11, 2, 9, tzinfo=UTC)),
    ],
    ids=["friday_plus_10", "wednesday_plus_1", "friday_plus_1"],
)
def test_business_days_skip_weekends(start, days, due):
    assert _add_business_days(start, days) == due


# Using a member who's turned off or being deleted


def test_completing_again_refuses_a_turned_off_member(client, headers):
    profile_id = add_member(client, headers)
    turn_off(client, headers, profile_id)

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "profile_turned_off",
        "message": "Azka’s profile is turned off.",
        "field": None,
    }


def test_completing_again_refuses_a_member_being_deleted(client, headers):
    profile_id = add_member(client, headers)
    remove(client, headers, profile_id)

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deletion_requested",
        "message": "Azka’s data is being deleted, so their profile can’t be used.",
        "field": None,
    }


# Which profiles these actions apply to


@pytest.mark.parametrize("action", list(CHANGES))
def test_own_profile_is_not_a_family_member(client, headers, action):
    response = act(client, headers, own_profile_id(client, headers), action)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_family_member"


@pytest.mark.parametrize("action", list(CHANGES))
def test_unfinished_family_draft_cannot_be_managed(client, headers, action):
    draft_id = client.post("/profiles/family", headers=headers).json()["profile_id"]

    response = act(client, headers, draft_id, action)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "intake_incomplete",
        "message": "Please finish adding this family member first.",
        "field": None,
    }


@pytest.mark.parametrize("action", list(ACTIONS))
def test_another_clients_member_is_not_found(client, make_user, sign_in, headers, action):
    profile_id = add_member(client, headers)
    make_user(email="maria@example.com", subscription_plan="basic")
    marias_headers = bearer(sign_in(email="maria@example.com")["access_token"])

    response = act(client, marias_headers, profile_id, action)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


# Record keeping


def test_audit_events_hold_no_names_or_values(client, db, headers):
    profile_id = add_member(client, headers)
    edit(
        client,
        headers,
        profile_id,
        {
            "first_name": "maya",
            "family_relationship": "partner",
            "advocate_consent": "authorised_to_act",
            "gender_identity": "other",
            "gender_identity_other": "Two-spirit",
        },
    )
    turn_off(client, headers, profile_id)
    remove(client, headers, profile_id, "Maya")

    found = db.scalars(select(AuditEvent).where(AuditEvent.target_id == profile_id)).all()

    assert {"profile.updated", "profile.turned_off", "profile.deletion_requested"} <= {
        event.action for event in found
    }
    flattened = str([event.details for event in found])
    for secret in ("Azka", "Maya", "maya", "Two-spirit", "child", "partner", "authorised_to_act"):
        assert secret not in flattened


def unfinished_family_member(db, user) -> Profile:
    profile = Profile(account_id=user.id, is_self=False)
    db.add(profile)
    db.flush()
    return profile


def test_database_refuses_a_deletion_request_on_an_unfinished_profile(db, make_user):
    profile = unfinished_family_member(db, make_user(subscription_plan="basic"))
    profile.deletion_requested_at = datetime.now(UTC)

    with pytest.raises(IntegrityError):
        db.flush()


def test_database_refuses_turning_off_an_unfinished_profile(db, make_user):
    profile = unfinished_family_member(db, make_user(subscription_plan="basic"))
    profile.turned_off_at = datetime.now(UTC)

    with pytest.raises(IntegrityError):
        db.flush()


def test_database_keeps_the_clients_own_profile_on(db, make_user):
    user = make_user()
    own = db.scalars(select(Profile).where(Profile.account_id == user.id, Profile.is_self)).one()
    own.turned_off_at = datetime.now(UTC)

    with pytest.raises(IntegrityError):
        db.flush()
