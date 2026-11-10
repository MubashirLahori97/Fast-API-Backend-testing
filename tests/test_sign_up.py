"""Story 1.1: Sign Up.

The account is created only when the emailed code is verified ("when they verify the code,
then their account is created"). Until then each sign-up waits as its own attempt, a
PendingSignUp, which is deleted if its code is never verified (docs/PLAN.md, R1: "Account
created at verification"). The limits on attempts are in tests/test_auth_limits.py.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import worker
from app.accounts.models import PolicyAcceptance, PolicyVersion
from app.auth import service as auth_service
from app.auth.jobs import purge_pending_sign_up
from app.auth.models import PendingSignUp, User, UserSession, VerificationChallenge
from app.auth.security import verify_password
from app.core import ages
from app.core.ages import today, us_today
from app.core.audit import AuditEvent
from app.core.config import settings
from app.core.jobs import Job
from tests.helpers import PASSWORD, PASSWORD_RULES, PASSWORDS_DONT_MATCH, bearer, last_code
from tests.test_policies import publish_terms

VALID = {
    "first_name": "Sarah",
    "date_of_birth": "1988-04-12",
    "country": "US",
    "state": "CA",
    "email": "Sarah@Example.com",
    "password": PASSWORD,
    "confirm_password": PASSWORD,
    "accept_terms": True,
}
INVALID_DATE_OF_BIRTH = "Please enter a valid date of birth."
INVALID_STATE = "Please enter a valid state."
UNDER_AGE = {
    "code": "under_age",
    "message": "Please ask a parent or guardian to add you as a family member.",
    "field": "date_of_birth",
}
EMAIL_TAKEN = {
    "code": "email_taken",
    "message": "An account with this email already exists. Please sign in.",
    "field": "email",
}
SIGN_UP_CODE_EXPIRED = {
    "code": "code_expired",
    "message": "Please request a new code.",
    "field": "code",
}
# Not in the stories: chosen in docs/PLAN.md (R1) for the per-IP limit.
TOO_MANY_ATTEMPTS = {
    "code": "too_many_attempts",
    "message": "Too many attempts. Please wait a few minutes and try again.",
    "field": None,
}
PURGE_JOB = "auth.purge_pending_sign_up"
OMIT = object()  # in a parametrized change: leave the field out of the body


def anniversary(day: date, years: int) -> date:
    """The same calendar date `years` earlier; 29 February falls back to the 28th."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def years_ago(years: int, plus_days: int = 0) -> str:
    """A date of birth for the age rules, which count from the date in Hawaii (us_today), the
    last US state to reach each new date. Building it from the UTC date would flake between
    00:00 and 10:00 UTC."""
    return (anniversary(us_today(), years) + timedelta(days=plus_days)).isoformat()


# The oldest date of birth accepted: 120 calendar years before the UTC date.
OLDEST_ALLOWED = anniversary(today(), 120)


class FrozenClock(datetime):
    """Stands in for datetime in app.core.ages, so "now" is a fixed moment."""

    moment = datetime(2026, 11, 5, 9, 59, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.moment.astimezone(tz)


def with_changes(body: dict, changes: dict) -> dict:
    merged = {**body, **changes}
    return {key: value for key, value in merged.items() if value is not OMIT}


def user_count(db) -> int:
    return db.scalar(select(func.count()).select_from(User))


def pending_count(db) -> int:
    return db.scalar(select(func.count()).select_from(PendingSignUp))


def nothing_saved(db) -> bool:
    """No account and no sign-up attempt."""
    return user_count(db) == 0 and pending_count(db) == 0


def attempts(db) -> list[PendingSignUp]:
    """Every sign-up attempt, oldest first, as saved now."""
    return list(
        db.scalars(
            select(PendingSignUp)
            .order_by(PendingSignUp.expires_at)
            .execution_options(populate_existing=True)
        )
    )


def the_pending(db) -> PendingSignUp:
    """The only sign-up attempt, as saved now."""
    [pending] = attempts(db)
    return pending


def the_user(db) -> User:
    return db.scalars(select(User).execution_options(populate_existing=True)).one()


def challenge_row(db, challenge: dict) -> VerificationChallenge:
    """The challenge as saved now."""
    return db.scalars(
        select(VerificationChallenge)
        .where(VerificationChallenge.id == uuid.UUID(challenge["challenge_id"]))
        .execution_options(populate_existing=True)
    ).one()


def events(db, action: str) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


def purge_jobs(db) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.kind == PURGE_JOB)))


def sign_up(client, **changes) -> dict:
    """Signs up with VALID (and any changes) and returns the challenge."""
    return client.post("/auth/signup", json={**VALID, **changes}).json()


def verify(client, challenge: dict, code: str):
    return client.post(
        "/auth/verify", json={"challenge_id": challenge["challenge_id"], "code": code}
    )


def signed_up(client, email_sender, **changes) -> tuple[dict, str]:
    """Signs up and returns the challenge and its code."""
    challenge = sign_up(client, **changes)
    return challenge, last_code(email_sender)


def expire(db, pending: PendingSignUp) -> None:
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()


# Steps 1 and 2 (date of birth and state): the same errors on sign-up and on the check.
DETAILS_ERRORS = [
    ({"date_of_birth": OMIT}, "date_of_birth", INVALID_DATE_OF_BIRTH),
    ({"date_of_birth": ""}, "date_of_birth", INVALID_DATE_OF_BIRTH),
    ({"date_of_birth": None}, "date_of_birth", INVALID_DATE_OF_BIRTH),
    ({"date_of_birth": "not a date"}, "date_of_birth", INVALID_DATE_OF_BIRTH),
    ({"date_of_birth": "1988-02-30"}, "date_of_birth", INVALID_DATE_OF_BIRTH),
    (
        {"date_of_birth": (today() + timedelta(days=1)).isoformat()},
        "date_of_birth",
        INVALID_DATE_OF_BIRTH,
    ),
    (
        {"date_of_birth": (OLDEST_ALLOWED - timedelta(days=1)).isoformat()},
        "date_of_birth",
        INVALID_DATE_OF_BIRTH,
    ),
    ({"state": ""}, "state", INVALID_STATE),
    ({"state": "XX"}, "state", INVALID_STATE),
    ({"state": "PR"}, "state", INVALID_STATE),
    ({"state": "California"}, "state", INVALID_STATE),
]
DETAILS_ERROR_IDS = [
    "dob-missing",
    "dob-empty",
    "dob-null",
    "dob-not-a-date",
    "dob-impossible-date",
    "dob-in-the-future",
    "dob-a-day-over-120-years-ago",
    "state-empty",
    "state-unknown",
    "state-territory",
    "state-full-name",
]


# Signing up: the form waits as a sign-up attempt, and a code is emailed


def test_sign_up_emails_a_code(client, email_sender):
    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "verification_required"
    assert body["purpose"] == "verify_email"
    assert [email.to for email in email_sender.sent] == ["sarah@example.com"]
    assert last_code(email_sender)


def test_sign_up_creates_no_account_until_the_code_is_verified(client, db):
    client.post("/auth/signup", json=VALID)

    assert user_count(db) == 0
    assert pending_count(db) == 1


def test_sign_up_saves_the_form_in_a_pending_sign_up(client, db):
    client.post("/auth/signup", json=VALID)

    pending = the_pending(db)
    assert pending.email == "sarah@example.com"
    assert pending.password_hash != PASSWORD
    assert verify_password(PASSWORD, pending.password_hash)[0]


def test_pending_sign_up_records_the_ip_address(client, db):
    client.post("/auth/signup", json=VALID)

    assert the_pending(db).ip_address == "testclient"  # TestClient's client host


def test_pending_sign_up_expires_after_60_minutes(client, db):
    client.post("/auth/signup", json=VALID)

    expected = datetime.now(UTC) + timedelta(minutes=settings.pending_sign_up_minutes)
    assert abs(the_pending(db).expires_at - expected) < timedelta(minutes=1)


def test_sign_up_stores_the_date_of_birth_and_where_the_client_lives(client, db):
    client.post("/auth/signup", json=VALID)

    pending = the_pending(db)
    assert (
        pending.first_name,
        pending.date_of_birth,
        pending.country,
        pending.state,
    ) == ("Sarah", date(1988, 4, 12), "US", "CA")


def test_sign_up_keeps_the_terms_and_privacy_versions_shown(client, db):
    client.post("/auth/signup", json=VALID)

    ids = the_pending(db).policy_version_ids
    kinds = set(db.scalars(select(PolicyVersion.kind).where(PolicyVersion.id.in_(ids))))
    assert len(ids) == 2
    assert kinds == {"terms", "privacy"}


def test_sign_up_code_belongs_to_the_pending_sign_up(client, db):
    challenge = sign_up(client)

    row = challenge_row(db, challenge)
    assert (row.pending_sign_up_id, row.user_id, row.purpose) == (
        the_pending(db).id,
        None,
        "verify_email",
    )


def test_sign_up_schedules_deleting_the_pending_sign_up(client, db):
    client.post("/auth/signup", json=VALID)

    pending = the_pending(db)
    [job] = purge_jobs(db)
    assert job.payload == {"pending_sign_up_id": str(pending.id)}
    assert job.run_at == pending.expires_at


def test_country_defaults_to_the_united_states(client, db):
    response = client.post("/auth/signup", json=with_changes(VALID, {"country": OMIT}))

    assert response.status_code == 201
    assert the_pending(db).country == "US"


def test_only_the_united_states_can_be_chosen(client, db):
    response = client.post("/auth/signup", json={**VALID, "country": "CA"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "country"
    assert nothing_saved(db)


def test_lowercase_state_is_stored_uppercase(client, db):
    client.post("/auth/signup", json={**VALID, "state": "ny"})

    assert the_pending(db).state == "NY"


def test_washington_dc_is_accepted(client):
    assert client.post("/auth/signup", json={**VALID, "state": "DC"}).status_code == 201


def test_a_zip_code_is_no_longer_taken(client, db, email_sender):
    """5 Nov stories: step 2 is country and state only, so a ZIP code is an unknown field."""
    response = client.post("/auth/signup", json={**VALID, "zip_code": "94103"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "zip_code"
    assert nothing_saved(db)
    assert email_sender.sent == []


def test_sign_up_is_audited(client, db):
    client.post("/auth/signup", json=VALID)

    pending_id = the_pending(db).id
    started = [(event.actor_id, event.details) for event in events(db, "auth.sign_up.started")]
    sent = [(event.actor_id, event.details) for event in events(db, "auth.code.sent")]
    assert started == [(pending_id, {})]
    assert sent == [(pending_id, {"purpose": "verify_email"})]


def test_nothing_is_audited_as_an_account_before_the_code(client, db):
    client.post("/auth/signup", json=VALID)

    assert events(db, "auth.signed_up") == []
    assert events(db, "policy.accepted") == []


# Each sign-up is its own attempt, even for the same email


def test_each_sign_up_is_a_separate_attempt(client, db):
    sign_up(client)

    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 201
    rows = attempts(db)
    assert [row.email for row in rows] == ["sarah@example.com", "sarah@example.com"]
    assert rows[0].id != rows[1].id


def test_each_attempt_gets_its_own_code(client, db, email_sender):
    first = sign_up(client)
    second = sign_up(client)

    first_row, second_row = challenge_row(db, first), challenge_row(db, second)

    assert first_row.id != second_row.id
    assert first_row.pending_sign_up_id != second_row.pending_sign_up_id
    assert len(email_sender.sent) == 2


def test_signing_up_again_leaves_the_earlier_code_open(client, db):
    first = sign_up(client)

    sign_up(client)

    assert challenge_row(db, first).used_at is None


def test_signing_up_again_leaves_the_earlier_attempt_as_it_was(client, db):
    sign_up(client)
    earlier = the_pending(db)
    before = (earlier.id, earlier.first_name, earlier.password_hash, earlier.expires_at)

    sign_up(client, first_name="Sally", password="Renewal#2027", confirm_password="Renewal#2027")

    oldest = attempts(db)[0]
    assert (oldest.id, oldest.first_name, oldest.password_hash, oldest.expires_at) == before


def test_earlier_attempts_code_still_works(client, email_sender):
    first, first_code = signed_up(client, email_sender)
    sign_up(client)

    response = verify(client, first, first_code)

    assert response.status_code == 200
    assert response.json()["status"] == "signed_in"


def test_the_attempt_verified_becomes_the_account(client, db, email_sender):
    first, first_code = signed_up(client, email_sender)
    first_id = the_pending(db).id
    sign_up(client, first_name="Sally")

    verify(client, first, first_code)

    user = the_user(db)
    assert (user.id, user.first_name) == (first_id, "Sarah")


# Verifying the code: the account is created


def test_valid_code_creates_the_account_and_signs_in(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)

    response = verify(client, challenge, code)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_in"
    assert body["access_token"]
    assert body["device_token"]
    assert client.get("/me", headers=bearer(body["access_token"])).json()["first_name"] == "Sarah"
    assert user_count(db) == 1


def test_account_gets_the_pending_sign_ups_id_and_details(client, db, email_sender):
    challenge, code = signed_up(client, email_sender, state="ny")
    pending = the_pending(db)
    pending_id, password_hash = pending.id, pending.password_hash

    verify(client, challenge, code)

    user = the_user(db)
    assert user.id == pending_id
    assert (
        user.email,
        user.first_name,
        user.date_of_birth,
        user.country,
        user.state,
        user.password_hash,
    ) == ("sarah@example.com", "Sarah", date(1988, 4, 12), "US", "NY", password_hash)


def test_valid_code_verifies_the_email(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    user = the_user(db)
    assert abs(user.email_verified_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_account_starts_its_wrong_code_count_when_created(client, db, email_sender):
    """password_changed_at starts the account's wrong-code locks, so the attempt's own wrong
    codes (whose actor id becomes the account's id) don't count towards them."""
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    user = the_user(db)
    assert user.password_changed_at == user.email_verified_at


def test_trial_starts_when_the_code_is_verified(client, db, email_sender, monkeypatch):
    challenge, code = signed_up(client, email_sender)
    # The code is entered 5 minutes after signing up (it lasts 10).
    later = datetime.now(UTC) + timedelta(minutes=5)
    monkeypatch.setattr(auth_service, "_now", lambda: later)

    verify(client, challenge, code)

    assert the_user(db).trial_ends_at == later + timedelta(days=settings.trial_days)


def test_verification_records_the_policy_versions_shown_at_sign_up(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)
    shown = set(the_pending(db).policy_version_ids)
    publish_terms(db)  # a new version, published before the code was entered

    verify(client, challenge, code)

    user = the_user(db)
    accepted = set(
        db.scalars(
            select(PolicyAcceptance.policy_version_id).where(PolicyAcceptance.user_id == user.id)
        )
    )
    assert accepted == shown


def test_policy_published_before_the_code_still_needs_accepting(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)
    publish_terms(db)

    token = verify(client, challenge, code).json()["access_token"]

    next_step = client.get("/me/next-step", headers=bearer(token)).json()["next_step"]
    assert next_step == "policy_update"


def test_verification_is_audited(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    user = the_user(db)
    signed_up_events = [
        (event.actor_id, event.target_type, event.target_id)
        for event in events(db, "auth.signed_up")
    ]
    assert signed_up_events == [(user.id, "user", str(user.id))]
    assert [event.actor_id for event in events(db, "auth.email_verified")] == [user.id]
    assert [event.actor_id for event in events(db, "policy.accepted")] == [user.id, user.id]


def test_verification_deletes_every_attempt_for_the_email(client, db, email_sender):
    sign_up(client)
    challenge, code = signed_up(client, email_sender)
    sign_up(client, email="maria@example.com", first_name="Maria")

    verify(client, challenge, code)

    assert [row.email for row in attempts(db)] == ["maria@example.com"]


def test_used_sign_up_code_moves_to_the_account(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    row = challenge_row(db, challenge)
    assert (row.user_id, row.pending_sign_up_id) == (the_user(db).id, None)
    assert row.used_at is not None


def test_other_attempts_codes_are_left_with_no_owner(client, db, email_sender):
    other = sign_up(client)
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    row = challenge_row(db, other)
    assert (row.user_id, row.pending_sign_up_id) == (None, None)


def test_another_attempts_code_after_the_account_exists_is_expired(client, email_sender):
    other, other_code = signed_up(client, email_sender)
    challenge, code = signed_up(client, email_sender)
    verify(client, challenge, code)

    response = verify(client, other, other_code)

    assert response.status_code == 400
    assert response.json()["error"] == SIGN_UP_CODE_EXPIRED


def test_device_is_trusted_after_sign_up(client, email_sender):
    challenge, code = signed_up(client, email_sender)
    device_token = verify(client, challenge, code).json()["device_token"]
    emails_before = len(email_sender.sent)

    body = client.post(
        "/auth/signin",
        json={"email": "sarah@example.com", "password": PASSWORD, "device_token": device_token},
    ).json()

    assert body["status"] == "signed_in"
    assert len(email_sender.sent) == emails_before  # no code asked for


# The email that tells the owner an account was created (from the security review: someone
# else may have verified a sign-up for their address)

WELCOME_SUBJECT = "Welcome to Your Oracle"
WELCOME_START = "An account with Your Oracle has just been created with this email address."


def test_verifying_a_sign_up_emails_the_owner(client, email_sender):
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, code)

    email = email_sender.sent[-1]
    assert (email.to, email.subject) == ("sarah@example.com", WELCOME_SUBJECT)
    assert email.body.startswith(WELCOME_START)


def test_verifying_a_sign_up_sends_only_the_welcome_email(client, email_sender):
    challenge, code = signed_up(client, email_sender)
    emails_before = len(email_sender.sent)

    verify(client, challenge, code)

    assert [email.subject for email in email_sender.sent[emails_before:]] == [WELCOME_SUBJECT]


def test_wrong_sign_up_code_sends_no_welcome_email(client, email_sender):
    challenge, code = signed_up(client, email_sender)

    verify(client, challenge, f"{(int(code) + 1) % 1_000_000:06d}")

    assert WELCOME_SUBJECT not in [email.subject for email in email_sender.sent]


def test_sign_up_refused_at_verification_sends_no_welcome_email(client, make_user, email_sender):
    challenge, code = signed_up(client, email_sender)
    make_user(email="sarah@example.com")

    verify(client, challenge, code)

    assert WELCOME_SUBJECT not in [email.subject for email in email_sender.sent]


def test_sign_in_code_sends_no_welcome_email(client, make_user, sign_in, email_sender):
    make_user()

    sign_in()

    assert WELCOME_SUBJECT not in [email.subject for email in email_sender.sent]


def test_email_that_got_an_account_meanwhile_is_refused_at_verification(
    client, db, make_user, email_sender
):
    challenge, code = signed_up(client, email_sender)
    make_user(email="sarah@example.com")

    response = verify(client, challenge, code)

    assert response.status_code == 409
    assert response.json()["error"] == EMAIL_TAKEN
    assert user_count(db) == 1
    assert db.scalars(select(UserSession)).first() is None


def test_me_leaves_out_the_sign_up_details_and_phone(client, email_sender):
    """/me answers before the policy gate, so it holds no personal details."""
    challenge, code = signed_up(client, email_sender)
    token = verify(client, challenge, code).json()["access_token"]

    me = client.get("/me", headers=bearer(token)).json()

    assert me["first_name"] == "Sarah"
    assert me["role"] == "client"  # admins come with Phase A
    assert {"phone", "date_of_birth", "country", "state", "zip_code"}.isdisjoint(me)


# An email that already has an account


def test_email_already_registered(client, make_user):
    make_user(email="sarah@example.com")

    response = client.post("/auth/signup", json={**VALID, "email": "SARAH@example.com"})

    assert response.status_code == 409
    assert response.json()["error"] == EMAIL_TAKEN


def test_email_already_registered_saves_no_pending_sign_up(client, db, make_user, email_sender):
    make_user(email="sarah@example.com")

    client.post("/auth/signup", json=VALID)

    assert pending_count(db) == 0
    assert email_sender.sent == []


def test_refused_sign_up_is_audited(client, db, make_user):
    existing = make_user(email="sarah@example.com")

    client.post("/auth/signup", json=VALID)

    [event] = events(db, "auth.sign_up.refused")
    assert (event.actor_id, event.target_type, event.target_id, event.details) == (
        None,
        "user",
        str(existing.id),
        {"reason": "email_taken"},
    )


# The per-IP sign-up limit


def test_refused_sign_ups_count_towards_the_ip_limit(client, make_user):
    make_user(email="sarah@example.com")
    for _ in range(settings.ip_failure_limit):
        assert client.post("/auth/signup", json=VALID).status_code == 409

    response = client.post("/auth/signup", json={**VALID, "email": "maria@example.com"})

    assert response.status_code == 429
    assert response.json()["error"] == TOO_MANY_ATTEMPTS


def test_started_sign_ups_count_towards_the_ip_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "ip_failure_limit", 3)
    for number in range(3):
        body = {**VALID, "email": f"client{number}@example.com"}
        assert client.post("/auth/signup", json=body).status_code == 201

    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 429
    assert response.json()["error"] == TOO_MANY_ATTEMPTS


def test_ip_limit_counts_sign_ups_and_refusals_together(client, db):
    half = settings.ip_failure_limit // 2
    for action in ["auth.sign_up.started"] * half + ["auth.sign_up.refused"] * (
        settings.ip_failure_limit - half
    ):
        db.add(AuditEvent(action=action, ip_address="testclient"))
    db.commit()

    response = client.post("/auth/signup", json=VALID)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert nothing_saved(db)


# Validation


@pytest.mark.parametrize(("changes", "field", "message"), DETAILS_ERRORS, ids=DETAILS_ERROR_IDS)
def test_sign_up_refuses_invalid_details(client, db, email_sender, changes, field, message):
    response = client.post("/auth/signup", json=with_changes(VALID, changes))

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)
    assert nothing_saved(db)
    assert email_sender.sent == []


@pytest.mark.parametrize(
    ("changes", "field", "message"),
    [
        ({"first_name": " "}, "first_name", "Please enter your first name."),
        ({"email": ""}, "email", "Email is required."),
        ({"email": "sarah@"}, "email", "Please enter a valid email address."),
        (
            {"password": "healing2026", "confirm_password": "healing2026"},
            "password",
            PASSWORD_RULES,
        ),
        ({"confirm_password": ""}, "confirm_password", PASSWORDS_DONT_MATCH),
        ({"confirm_password": "Healing!2027"}, "confirm_password", PASSWORDS_DONT_MATCH),
        (
            {"accept_terms": False},
            "accept_terms",
            "Please accept the Terms of Service and Privacy Policy to continue.",
        ),
    ],
    ids=[
        "first-name-empty",
        "email-empty",
        "email-invalid",
        "weak-password",
        "confirm-empty",
        "confirm-mismatch",
        "terms-not-accepted",
    ],
)
def test_sign_up_validation(client, db, email_sender, changes, field, message):
    response = client.post("/auth/signup", json={**VALID, **changes})

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)
    assert nothing_saved(db)
    assert email_sender.sent == []


def test_missing_fields_get_the_story_messages(client):
    response = client.post("/auth/signup", json={})

    details = response.json()["error"]["details"]
    assert {"field": "date_of_birth", "message": INVALID_DATE_OF_BIRTH} in details
    assert {"field": "state", "message": INVALID_STATE} in details
    assert "zip_code" not in {detail["field"] for detail in details}
    assert {"field": "email", "message": "Email is required."} in details
    assert {"field": "password", "message": PASSWORD_RULES} in details
    assert {"field": "confirm_password", "message": PASSWORDS_DONT_MATCH} in details


def test_sign_up_rejects_fields_clients_may_not_set(client, db):
    response = client.post("/auth/signup", json={**VALID, "role": "super_admin"})

    assert response.status_code == 422
    assert nothing_saved(db)


def test_sign_up_rejects_a_phone_number(client, db):
    response = client.post("/auth/signup", json={**VALID, "phone": "(650) 253-0000"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "phone"
    assert nothing_saved(db)


def test_client_under_18_is_refused_and_nothing_is_saved(client, db, email_sender):
    response = client.post(
        "/auth/signup", json={**VALID, "date_of_birth": years_ago(18, plus_days=1)}
    )

    assert response.status_code == 422
    assert response.json()["error"] == UNDER_AGE
    assert nothing_saved(db)
    assert email_sender.sent == []


def test_client_who_turns_18_today_can_sign_up(client):
    response = client.post("/auth/signup", json={**VALID, "date_of_birth": years_ago(18)})

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("path", "status"),
    [("/auth/signup", 201), ("/auth/signup/check", 204)],
    ids=["sign-up", "check"],
)
def test_date_of_birth_exactly_120_years_ago_is_accepted(client, path, status):
    response = client.post(path, json={**VALID, "date_of_birth": OLDEST_ALLOWED.isoformat()})

    assert response.status_code == status


def test_18th_birthday_doesnt_count_until_it_has_started_in_hawaii(client, monkeypatch):
    # 09:59 UTC on 5 Nov is still 4 Nov in Hawaii (UTC-10).
    monkeypatch.setattr(ages, "datetime", FrozenClock)

    response = client.post("/auth/signup/check", json={**VALID, "date_of_birth": "2008-11-05"})

    assert response.status_code == 422
    assert response.json()["error"] == UNDER_AGE


def test_18th_birthday_counts_once_it_has_started_in_hawaii(client, monkeypatch):
    monkeypatch.setattr(FrozenClock, "moment", datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(ages, "datetime", FrozenClock)

    response = client.post("/auth/signup/check", json={**VALID, "date_of_birth": "2008-11-05"})

    assert response.status_code == 204


def test_age_of_majority_is_a_setting(client, db, monkeypatch):
    monkeypatch.setattr(settings, "age_of_majority", 21)

    response = client.post("/auth/signup", json={**VALID, "date_of_birth": years_ago(20)})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "under_age"
    assert nothing_saved(db)


@pytest.mark.parametrize(
    "password",
    ["Sh0rt!", "healing!2026", "HEALING!2026", "Healing!!!!", "Healing2026"],
    ids=["too-short", "no-uppercase", "no-lowercase", "no-number", "no-special"],
)
def test_each_password_rule_is_enforced(client, password):
    response = client.post(
        "/auth/signup", json={**VALID, "password": password, "confirm_password": password}
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == PASSWORD_RULES


# Leaving before verifying


def test_signing_in_before_verifying_finds_no_account(client, email_sender):
    sign_up(client)

    response = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "invalid_credentials",
        "message": "Incorrect email or password. Please try again.",
        "field": None,
    }
    assert len(email_sender.sent) == 1  # only the sign-up's code


def test_client_who_left_before_verifying_signs_up_again(client, email_sender):
    sign_up(client)

    challenge, code = signed_up(client, email_sender)
    response = verify(client, challenge, code)

    assert response.json()["status"] == "signed_in"


# Attempts that are never verified are deleted (the purge job)


def purge(db, pending_id: uuid.UUID) -> None:
    """Runs the purge job's handler, then commits, as the worker does."""
    purge_pending_sign_up(db, {"pending_sign_up_id": str(pending_id)})
    db.commit()


def test_expired_attempt_is_deleted(client, db):
    sign_up(client)
    pending = the_pending(db)
    pending_id = pending.id
    expire(db, pending)

    purge(db, pending_id)

    assert pending_count(db) == 0


def test_purge_deletes_every_expired_attempt(client, db):
    sign_up(client)
    sign_up(client, email="maria@example.com", first_name="Maria")
    sarahs, marias = attempts(db)
    for pending in (sarahs, marias):
        expire(db, pending)

    purge(db, sarahs.id)

    assert pending_count(db) == 0


def test_purge_keeps_attempts_that_havent_expired(client, db):
    sign_up(client)
    sign_up(client, email="maria@example.com", first_name="Maria")
    sarahs, _ = attempts(db)
    expire(db, sarahs)

    purge(db, sarahs.id)

    assert [row.email for row in attempts(db)] == ["maria@example.com"]


def test_purged_attempts_code_is_kept_with_no_owner(client, db):
    challenge = sign_up(client)
    pending = the_pending(db)
    expire(db, pending)

    purge(db, pending.id)

    row = challenge_row(db, challenge)
    assert (row.user_id, row.pending_sign_up_id) == (None, None)


def owner_less_code(client, db, age: timedelta) -> dict:
    """A sign-up code whose attempt was purged, made `age` ago."""
    challenge = sign_up(client)
    pending = the_pending(db)
    expire(db, pending)
    purge(db, pending.id)
    challenge_row(db, challenge).created_at = datetime.now(UTC) - age
    db.commit()
    return challenge


def code_exists(db, challenge: dict) -> bool:
    """Asks the database, not the session, which may still hold a deleted row."""
    challenge_id = uuid.UUID(challenge["challenge_id"])
    found = db.scalar(
        select(VerificationChallenge.id).where(VerificationChallenge.id == challenge_id)
    )
    return found is not None


def test_purge_deletes_owner_less_codes_over_a_day_old(client, db):
    challenge = owner_less_code(client, db, timedelta(hours=25))

    purge(db, uuid.uuid4())  # the job of any attempt

    assert not code_exists(db, challenge)


def test_purge_keeps_owner_less_codes_under_a_day_old(client, db):
    challenge = owner_less_code(client, db, timedelta(hours=23))

    purge(db, uuid.uuid4())

    assert code_exists(db, challenge)


def test_purge_keeps_an_accounts_old_codes(client, db, make_user):
    make_user()
    challenge = client.post(
        "/auth/signin", json={"email": "sarah@example.com", "password": PASSWORD}
    ).json()
    challenge_row(db, challenge).created_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()

    purge(db, uuid.uuid4())

    assert code_exists(db, challenge)


def test_code_of_a_purged_attempt_is_expired(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)
    pending = the_pending(db)
    expire(db, pending)
    purge(db, pending.id)

    response = verify(client, challenge, code)

    assert response.status_code == 400
    assert response.json()["error"] == SIGN_UP_CODE_EXPIRED


def test_purge_runs_again_for_an_attempt_that_hasnt_expired(client, db):
    sign_up(client)
    pending = the_pending(db)
    later = datetime.now(UTC) + timedelta(minutes=30)  # as if a resend had kept it longer
    pending.expires_at = later
    db.commit()

    purge(db, pending.id)

    assert pending_count(db) == 1
    [again] = [job for job in purge_jobs(db) if job.run_at == later]
    assert again.payload == {"pending_sign_up_id": str(pending.id)}


def test_purge_of_a_verified_sign_up_does_nothing_more(client, db, email_sender):
    challenge, code = signed_up(client, email_sender)
    pending_id = the_pending(db).id
    verify(client, challenge, code)
    jobs_before = len(purge_jobs(db))

    purge(db, pending_id)

    assert user_count(db) == 1
    assert len(purge_jobs(db)) == jobs_before


def test_the_worker_deletes_an_expired_attempt(client, db):
    sign_up(client)
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    the_pending(db).expires_at = long_ago
    [job] = purge_jobs(db)
    job.run_at = long_ago
    db.commit()

    assert worker.run_once(db) is True

    db.refresh(job)
    assert job.status == "done"
    assert pending_count(db) == 0


def test_the_worker_knows_the_purge_job():
    worker.load_handlers()

    assert worker.HANDLERS[PURGE_JOB] is purge_pending_sign_up


# No unverified accounts


def test_database_refuses_an_account_without_a_verified_email(db):
    db.add(
        User(
            email="sarah@example.com",
            first_name="Sarah",
            password_hash="not a real hash",
            trial_ends_at=datetime.now(UTC) + timedelta(days=14),
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


# The step 2 check: POST /auth/signup/check


def test_check_accepts_valid_details_of_an_adult(client):
    response = client.post(
        "/auth/signup/check",
        json={"date_of_birth": "1988-04-12", "country": "US", "state": "CA"},
    )

    assert response.status_code == 204


def test_check_ignores_the_other_sign_up_fields(client):
    response = client.post("/auth/signup/check", json={**VALID, "phone": "(650) 253-0000"})

    assert response.status_code == 204


@pytest.mark.parametrize(("changes", "field", "message"), DETAILS_ERRORS, ids=DETAILS_ERROR_IDS)
def test_check_refuses_invalid_details(client, changes, field, message):
    response = client.post("/auth/signup/check", json=with_changes(VALID, changes))

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["field"], error["message"]) == (field, message)


def test_check_refuses_another_country(client):
    response = client.post("/auth/signup/check", json={**VALID, "country": "CA"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "country"


def test_check_refuses_a_client_under_18(client):
    response = client.post(
        "/auth/signup/check", json={**VALID, "date_of_birth": years_ago(18, plus_days=1)}
    )

    assert response.status_code == 422
    assert response.json()["error"] == UNDER_AGE


def test_check_lets_through_a_client_who_turns_18_today(client):
    response = client.post("/auth/signup/check", json={**VALID, "date_of_birth": years_ago(18)})

    assert response.status_code == 204


@pytest.mark.parametrize(
    "date_of_birth", ["1988-04-12", years_ago(18, plus_days=1)], ids=["adult", "under-age"]
)
def test_check_saves_nothing(client, db, email_sender, date_of_birth):
    events_before = db.scalar(select(func.count()).select_from(AuditEvent))

    client.post("/auth/signup/check", json={**VALID, "date_of_birth": date_of_birth})

    assert nothing_saved(db)
    assert db.scalar(select(func.count()).select_from(AuditEvent)) == events_before
    assert email_sender.sent == []
