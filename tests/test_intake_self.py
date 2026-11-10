"""Story 2.1: Complete Guided Health Intake - Myself."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.helpers import bearer

ANSWERS = [
    {"date_of_birth": "1990-03-14"},
    {"sex_at_birth": "female"},
    {"gender_identity": "woman"},
    {"pronouns": "she_her"},
]


@pytest.fixture
def headers(make_user, sign_in) -> dict[str, str]:
    """A brand-new client, signed in, who hasn't started the intake. The account was made
    before 4 Nov, so it has no date of birth from sign-up and the intake takes any date."""
    make_user(intake_done=False, date_of_birth=None)
    return bearer(sign_in()["access_token"])


@pytest.fixture
def signed_up_headers(make_user, sign_in) -> dict[str, str]:
    """Like headers, for an account that gave its date of birth (1988-04-12) at sign-up."""
    make_user(intake_done=False, date_of_birth=date(1988, 4, 12))
    return bearer(sign_in()["access_token"])


def start(client, headers) -> dict:
    return client.post("/profiles/self", headers=headers).json()


def answer(client, headers, profile_id, body):
    return client.patch(f"/profiles/{profile_id}/intake", headers=headers, json=body)


def years_ago(years: int, days: int = 0) -> str:
    """The date `years` ago today (28 Feb when today is 29 Feb and that year has none)."""
    today = datetime.now(UTC).date()
    try:
        then = today.replace(year=today.year - years)
    except ValueError:  # 29 February in a year without one
        then = today.replace(year=today.year - years, day=28)
    return (then + timedelta(days=days)).isoformat()


def test_new_client_is_sent_to_the_intake(client, headers):
    assert client.get("/me/next-step", headers=headers).json() == {
        "next_step": "intake",
        "profile_id": None,
    }


def test_for_myself_starts_the_intake(client, headers):
    response = client.post("/profiles/self", headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["is_self"] is True
    assert body["next_question"] == "date_of_birth"
    assert body["completed"] is False


def test_starting_again_returns_the_same_profile(client, headers):
    first = start(client, headers)

    again = client.post("/profiles/self", headers=headers)

    assert again.status_code == 200
    assert again.json()["profile_id"] == first["profile_id"]


def test_each_step_moves_to_the_next_question(client, headers):
    profile_id = start(client, headers)["profile_id"]

    questions = [
        answer(client, headers, profile_id, body).json()["next_question"] for body in ANSWERS
    ]

    assert questions == ["sex_at_birth", "gender_identity", "pronouns", "done"]


def test_completing_greets_the_client_by_first_name(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in ANSWERS:
        answer(client, headers, profile_id, body)

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "profile_id": profile_id,
        "message": "Thank you, Sarah. I’m so glad you’re here. "
        "Tell me what’s on your mind, and I’ll ask what I need as we go.",
    }
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "dashboard"


def test_leaving_midway_resumes_at_the_same_question(client, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, ANSWERS[0])
    answer(client, headers, profile_id, ANSWERS[1])

    next_step = client.get("/me/next-step", headers=headers).json()
    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()

    assert next_step == {"next_step": "intake", "profile_id": profile_id}
    assert intake["next_question"] == "gender_identity"
    assert intake["sex_at_birth"] == "female"  # earlier answers are kept


def test_back_button_changes_an_earlier_answer(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in ANSWERS[:3]:
        answer(client, headers, profile_id, body)

    changed = answer(client, headers, profile_id, {"sex_at_birth": "intersex"}).json()

    assert changed["sex_at_birth"] == "intersex"
    assert changed["next_question"] == "pronouns"


def test_cannot_complete_with_a_step_unanswered(client, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, ANSWERS[0])

    response = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "sex_at_birth"


def test_future_date_of_birth_is_refused(client, headers):
    profile_id = start(client, headers)["profile_id"]
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    response = answer(client, headers, profile_id, {"date_of_birth": tomorrow})

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Please choose a date that isn’t in the future."


def test_under_13_cannot_have_their_own_profile(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, {"date_of_birth": years_ago(13, days=1)})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "under_13",
        "message": "I’m so glad you’re interested! You’ll need to be 13 or older to have your "
        "own account, so please ask a parent or guardian to add you as a family member.",
        "field": "date_of_birth",
    }


def test_13_today_is_old_enough(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, {"date_of_birth": years_ago(13)})

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        (
            {"gender_identity": "other", "gender_identity_other": " "},
            "gender_identity_other",
            "Tell me in your own words how you identify.",
        ),
        (
            {"pronouns": "other"},
            "pronouns_other",
            "Tell me which pronouns you’d like me to use.",
        ),
    ],
    ids=["gender", "pronouns"],
)
def test_other_needs_a_write_in(client, headers, body, field, message):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, body)

    assert response.status_code == 422
    assert (response.json()["error"]["field"], response.json()["error"]["message"]) == (
        field,
        message,
    )


def test_other_with_a_write_in_is_saved(client, headers):
    profile_id = start(client, headers)["profile_id"]

    body = answer(
        client,
        headers,
        profile_id,
        {"gender_identity": "other", "gender_identity_other": "Two-spirit"},
    ).json()

    assert (body["gender_identity"], body["gender_identity_other"]) == ("other", "Two-spirit")


def test_changing_away_from_other_clears_the_write_in(client, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, {"pronouns": "other", "pronouns_other": "xe/xem"})

    body = answer(client, headers, profile_id, {"pronouns": "they_them"}).json()

    assert body["pronouns_other"] is None


def test_unknown_option_is_refused(client, headers):
    profile_id = start(client, headers)["profile_id"]

    assert answer(client, headers, profile_id, {"sex_at_birth": "unknown"}).status_code == 422


def test_completed_intake_cannot_be_changed_here(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in ANSWERS:
        answer(client, headers, profile_id, body)
    client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    response = answer(client, headers, profile_id, {"pronouns": "they_them"})

    assert response.status_code == 409


def test_profiles_list_shows_the_client_as_themself(client, headers):
    start(client, headers)

    profiles = client.get("/profiles", headers=headers).json()

    assert [(p["is_self"], p["first_name"]) for p in profiles] == [(True, "Sarah")]


def test_age_is_worked_out_from_the_date_of_birth(client, headers):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, {"date_of_birth": years_ago(30)})

    assert client.get("/profiles", headers=headers).json()[0]["age"] == 30


def test_another_clients_profile_is_not_found(client, make_user, sign_in, headers):
    sarahs_profile = start(client, headers)["profile_id"]
    make_user(email="maria@example.com")
    marias_headers = bearer(sign_in(email="maria@example.com")["access_token"])

    for response in (
        client.get(f"/profiles/{sarahs_profile}/intake", headers=marias_headers),
        answer(client, marias_headers, sarahs_profile, {"sex_at_birth": "male"}),
        client.post(f"/profiles/{sarahs_profile}/intake/complete", headers=marias_headers),
    ):
        assert response.status_code == 404


def test_date_of_birth_is_a_real_date(client, headers):
    profile_id = start(client, headers)["profile_id"]

    assert answer(client, headers, profile_id, {"date_of_birth": "1990-02-30"}).status_code == 422


def test_intake_needs_a_signed_in_client(client):
    assert client.post("/profiles/self").status_code == 401


def test_profile_endpoints_wait_for_updated_policies(client, db, headers):
    from app.accounts.models import PolicyVersion

    db.add(
        PolicyVersion(
            kind="privacy",
            version="2.0",
            title="Privacy Policy",
            published_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db.commit()

    response = client.post("/profiles/self", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy_update_required"
    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "policy_update"


def test_reaching_13_today_counts_by_calendar_date():
    from app.profiles.service import age_on

    assert age_on(date(2013, 10, 30), date(2026, 10, 30)) == 13
    assert age_on(date(2013, 10, 31), date(2026, 10, 30)) == 12


def test_leap_day_birthdays():
    from app.profiles.service import age_on

    assert age_on(date(2012, 2, 29), date(2025, 2, 28)) == 12
    assert age_on(date(2012, 2, 29), date(2025, 3, 1)) == 13


# Every profile and conversation route, which the policy gate must cover. Paths leave out the
# /api/v1 prefix (the client fixture adds it), and every path parameter is written {id}.
GATED_ROUTES = [
    ("get", "/profiles"),
    ("post", "/profiles/self"),
    ("get", "/profiles/family"),
    ("post", "/profiles/family"),
    ("get", "/profiles/{id}"),
    ("patch", "/profiles/{id}"),
    ("delete", "/profiles/{id}"),
    ("get", "/profiles/{id}/intake"),
    ("patch", "/profiles/{id}/intake"),
    ("post", "/profiles/{id}/intake/complete"),
    ("post", "/profiles/{id}/turn-off"),
    ("post", "/profiles/{id}/turn-on"),
    ("post", "/profiles/{id}/deletion-request"),
    ("get", "/profiles/{id}/conversations"),
    ("get", "/profiles/{id}/conversations/new"),
    ("post", "/profiles/{id}/conversations"),
    ("get", "/profiles/{id}/health-consent"),
    ("post", "/profiles/{id}/health-consent"),
    # The policies are checked before the conversation or message is looked up, so any id
    # will do.
    ("get", "/conversations/{id}"),
    ("delete", "/conversations/{id}"),
    ("post", "/conversations/{id}/messages"),
    ("post", "/conversations/{id}/reply"),
    ("put", "/conversations/{id}/messages/{id}/feedback"),
    ("delete", "/conversations/{id}/messages/{id}/feedback"),
]


def test_the_policy_gate_list_names_every_profile_and_conversation_route():
    """Keeps GATED_ROUTES complete when routes are added. Read from the OpenAPI schema, whose
    paths include the /api/v1 prefix."""
    import re

    from app.main import app

    routes = {
        (method, re.sub(r"\{\w+\}", "{id}", path.removeprefix("/api/v1")))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(("/api/v1/profiles", "/api/v1/conversations"))
        for method in operations
    }

    assert routes == set(GATED_ROUTES)


@pytest.mark.parametrize(("method", "path"), GATED_ROUTES)
def test_every_profile_route_waits_for_updated_policies(client, db, headers, method, path):
    from app.accounts.models import PolicyVersion

    profile_id = start(client, headers)["profile_id"]
    db.add(
        PolicyVersion(
            kind="terms",
            version="2.0",
            title="Terms of Service",
            published_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db.commit()

    response = client.request(
        method, path.format(id=profile_id), headers=headers, json={"pronouns": "she_her"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy_update_required"


@pytest.mark.parametrize(
    "body",
    [{"is_self": False}, {"intake_completed_at": "2026-01-01T00:00:00Z"}, {"account_id": "x"}],
    ids=["is_self", "intake_completed_at", "account_id"],
)
def test_protected_fields_cannot_be_set(client, headers, body):
    profile_id = start(client, headers)["profile_id"]

    response = answer(client, headers, profile_id, body)

    assert response.status_code == 422
    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()
    assert intake["is_self"] is True
    assert intake["completed"] is False


def test_under_13_refusal_saves_nothing_and_is_recorded(client, db, headers):
    from sqlalchemy import select

    from app.core.audit import AuditEvent

    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, {"date_of_birth": years_ago(10)})

    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()
    assert (intake["date_of_birth"], intake["next_question"]) == (None, "date_of_birth")
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "profile.under_13_refused")
    ).one()
    assert event.details == {}  # no date of birth in the audit log


def test_all_answered_but_not_completed_still_needs_the_intake(client, headers):
    profile_id = start(client, headers)["profile_id"]
    for body in ANSWERS:
        answer(client, headers, profile_id, body)

    next_step = client.get("/me/next-step", headers=headers).json()
    intake = client.get(f"/profiles/{profile_id}/intake", headers=headers).json()

    assert next_step == {"next_step": "intake", "profile_id": profile_id}
    assert intake["next_question"] == "done"


def test_completing_twice_is_fine_and_audited_once(client, db, headers):
    from sqlalchemy import select

    from app.core.audit import AuditEvent

    profile_id = start(client, headers)["profile_id"]
    for body in ANSWERS:
        answer(client, headers, profile_id, body)

    first = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)
    second = client.post(f"/profiles/{profile_id}/intake/complete", headers=headers)

    assert first.status_code == second.status_code == 200
    completed = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "profile.intake_completed")
    ).all()
    assert len(completed) == 1


def test_intake_audit_events_hold_no_health_data(client, db, headers):
    from sqlalchemy import select

    from app.core.audit import AuditEvent

    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, ANSWERS[0])

    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "profile.intake_answered")
    ).one()
    assert event.details == {"fields": ["date_of_birth"]}
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == profile_id)))
    assert "profile.created" in actions


def test_unfinished_intake_comes_before_the_upgrade_screen(client, db, make_user, sign_in):
    user = make_user(intake_done=False)
    user.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    headers = bearer(sign_in()["access_token"])

    assert client.get("/me/next-step", headers=headers).json()["next_step"] == "intake"


def test_date_of_birth_must_match_the_one_given_at_sign_up(client, signed_up_headers):
    profile_id = start(client, signed_up_headers)["profile_id"]

    response = answer(client, signed_up_headers, profile_id, {"date_of_birth": "1990-03-14"})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "date_of_birth_mismatch",
        "message": "Please enter the date of birth you gave when you signed up.",
        "field": "date_of_birth",
    }


def test_mismatched_date_of_birth_saves_nothing(client, signed_up_headers):
    profile_id = start(client, signed_up_headers)["profile_id"]

    answer(
        client,
        signed_up_headers,
        profile_id,
        {"date_of_birth": "1990-03-14", "sex_at_birth": "female"},
    )

    intake = start(client, signed_up_headers)
    assert (intake["date_of_birth"], intake["sex_at_birth"]) == (None, None)


def test_date_of_birth_given_at_sign_up_is_accepted(client, signed_up_headers):
    profile_id = start(client, signed_up_headers)["profile_id"]

    response = answer(client, signed_up_headers, profile_id, {"date_of_birth": "1988-04-12"})

    assert response.status_code == 200
    assert response.json()["date_of_birth"] == "1988-04-12"


def test_new_sign_up_goes_straight_to_the_intake(client, email_sender):
    from tests.helpers import last_code
    from tests.test_sign_up import VALID

    challenge = client.post("/auth/signup", json=VALID).json()
    token = client.post(
        "/auth/verify",
        json={"challenge_id": challenge["challenge_id"], "code": last_code(email_sender)},
    ).json()["access_token"]

    assert client.get("/me/next-step", headers=bearer(token)).json() == {
        "next_step": "intake",
        "profile_id": None,
    }


@pytest.mark.parametrize("body", [{"sex_at_birth": None}, {}], ids=["null", "empty"])
def test_nulls_and_empty_bodies_dont_unanswer(client, headers, body):
    profile_id = start(client, headers)["profile_id"]
    answer(client, headers, profile_id, {"sex_at_birth": "female"})

    response = answer(client, headers, profile_id, body)

    assert response.json()["sex_at_birth"] == "female"


def test_gender_write_in_is_trimmed_and_cleared(client, headers):
    profile_id = start(client, headers)["profile_id"]

    trimmed = answer(
        client,
        headers,
        profile_id,
        {"gender_identity": "other", "gender_identity_other": "  Two-spirit  "},
    ).json()
    cleared = answer(client, headers, profile_id, {"gender_identity": "woman"}).json()

    assert trimmed["gender_identity_other"] == "Two-spirit"
    assert cleared["gender_identity_other"] is None


def test_oversized_write_in_is_refused(client, headers):
    profile_id = start(client, headers)["profile_id"]

    response = answer(
        client, headers, profile_id, {"pronouns": "other", "pronouns_other": "x" * 1001}
    )

    assert response.status_code == 422


def test_unknown_profile_gets_the_same_404(client, headers):
    import uuid

    response = client.get(f"/profiles/{uuid.uuid4()}/intake", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "profile_not_found",
        "message": "We couldn’t find that profile.",
        "field": None,
    }
