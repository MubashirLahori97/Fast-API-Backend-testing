"""Shared test fixtures.

Tests use their own database, named after the dev database plus "_test". It's dropped and
rebuilt from the migrations at the start of every run, so the migrations are tested too.
Each test runs inside a transaction that's rolled back afterwards, even when the code under
test commits, so tests never see each other's data.
"""

import re
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.accounts import service as accounts_service
from app.auth.models import User
from app.auth.security import hash_password
from app.core.config import settings
from app.core.database import get_db
from app.core.email import InMemoryEmailSender, get_email_sender
from app.main import app
from app.oracle.dependencies import get_oracle
from app.oracle.fake import FakeOracle
from app.profiles.models import Profile
from tests.helpers import PASSWORD, last_code

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    dev_url = make_url(settings.database_url)
    test_url = dev_url.set(database=f"{dev_url.database}_test")
    # Never drop anything that isn't a *_test database.
    assert re.fullmatch(r"\w+_test", test_url.database or ""), test_url.database

    admin = create_engine(dev_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{test_url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    admin.dispose()

    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = test_url.render_as_string(hide_password=False)
    command.upgrade(config, "head")

    test_engine = create_engine(test_url, hide_parameters=True)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose changes are all rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def email_sender() -> InMemoryEmailSender:
    """Collects the emails the app sends during a test: email_sender.sent"""
    return InMemoryEmailSender()


@pytest.fixture
def oracle() -> FakeOracle:
    """The Oracle the app talks to during a test. Set oracle.reply, oracle.safety or
    oracle.fail_after to change what it does; oracle.calls lists what the app asked it."""
    return FakeOracle()


@pytest.fixture
def client(
    db: Session, email_sender: InMemoryEmailSender, oracle: FakeOracle
) -> Iterator[TestClient]:
    """Calls the API in-process, using the test session, the in-memory email sender and the
    fake Oracle."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_oracle] = lambda: oracle
    # Every endpoint is under /api/v1 (app/main.py), so tests write paths without it.
    with TestClient(app, base_url="http://testserver/api/v1") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    """Creates a client who has verified their email, accepted the current policies and
    finished their own health intake (pass intake_done=False for a brand-new client).
    The password is tests.helpers.PASSWORD unless you pass another.

    Every account has a verified email (story 1.1: it's created when the code is verified),
    so there's no option for an unverified one. A sign-up still waiting for its code is a
    PendingSignUp: make one through POST /auth/signup."""

    def make(
        email: str = "sarah@example.com",
        password: str = PASSWORD,
        intake_done: bool = True,
        **fields,
    ) -> User:
        now = datetime.now(UTC)
        details = {
            "first_name": "Sarah",
            "date_of_birth": date(1988, 4, 12),
            "country": "US",
            "state": "CA",
        }
        user = User(
            email=email,
            password_hash=hash_password(password),
            email_verified_at=now,
            trial_ends_at=now + timedelta(days=14),
            **(details | fields),
        )
        db.add(user)
        db.flush()
        accounts_service.record_acceptances(db, user, accounts_service.current_policies(db))
        if intake_done:
            db.add(
                Profile(
                    account_id=user.id,
                    is_self=True,
                    date_of_birth=date(1988, 4, 12),
                    sex_at_birth="female",
                    gender_identity="woman",
                    pronouns="she_her",
                    intake_completed_at=now,
                )
            )
        db.commit()
        return user

    return make


@pytest.fixture
def sign_in(client: TestClient, email_sender: InMemoryEmailSender) -> Callable[..., dict]:
    """Signs in through the API, entering the emailed code if asked. Returns the last body.
    Pass platform="mobile" for a mobile session; without it the app's default (web) applies."""

    def do(
        email: str = "sarah@example.com",
        password: str = PASSWORD,
        device_token: str | None = None,
        platform: str | None = None,
    ) -> dict:
        extra = {} if platform is None else {"platform": platform}
        body = client.post(
            "/auth/signin",
            json={"email": email, "password": password, "device_token": device_token} | extra,
        ).json()
        if body.get("status") == "verification_required":
            body = client.post(
                "/auth/verify",
                json={"challenge_id": body["challenge_id"], "code": last_code(email_sender)}
                | extra,
            ).json()
        return body

    return do
