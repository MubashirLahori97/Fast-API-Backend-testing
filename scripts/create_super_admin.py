"""Create the one Super Admin account (Super Admin 1.1: "set up once ... It isn't created
through sign-up or an invitation").

Usage, from the repo root, with the database migrated:

    uv run python scripts/create_super_admin.py --email deborah@example.com \
        --first-name Deborah --last-name Maragopoulos

The password is asked for twice at the prompt and never echoed; it's never taken from the
command line or the code, so it can't end up in shell history or the repository. It must follow
the password rules (8+ characters, an uppercase and a lowercase letter, a number and a special
character). The Super Admin then signs in at the admin panel with this email, the password and
an emailed code.

Refuses if a Super Admin already exists (the database also allows only one) or the email is
already used.
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path

# Lets `python scripts/create_super_admin.py` import the app from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import app.models  # noqa: E402, F401  (every table, so relationships resolve)
from app.auth.models import User  # noqa: E402
from app.auth.schemas import PASSWORD_RULES, normalize_email  # noqa: E402
from app.auth.security import hash_password, meets_password_rules  # noqa: E402
from app.core import audit  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.schemas import clean_name  # noqa: E402


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _name(value: str, label: str) -> str:
    try:
        name = clean_name(value)
    except ValueError as error:
        _fail(f"{label}: {error}")
    if not name:
        _fail(f"Please enter the {label.lower()}.")
    return name


def _password() -> str:
    password = getpass.getpass("Password: ")
    if not meets_password_rules(password):
        _fail(PASSWORD_RULES)
    if getpass.getpass("Confirm password: ") != password:
        _fail("The passwords don’t match.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the Super Admin account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    args = parser.parse_args()

    try:
        email = normalize_email(args.email, "Email is required.")
    except ValueError as error:
        _fail(str(error))
    first_name = _name(args.first_name, "First name")
    last_name = _name(args.last_name, "Last name")

    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.role == "super_admin")) is not None:
            _fail("A Super Admin already exists. There can only be one.")
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            _fail("An account with this email address already exists.")
        password = _password()
        now = datetime.now(UTC)
        user = User(
            role="super_admin",
            email=email,
            first_name=first_name,
            last_name=last_name,
            password_hash=hash_password(password),
            # Set up by the team, who confirm the address; the first sign-in emails a code to
            # it, which proves it again.
            email_verified_at=now,
            trial_ends_at=now,  # required for every account; there's no trial
            password_changed_at=now,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            _fail("A Super Admin or an account with this email already exists.")
        audit.record(
            db,
            "admin.super_admin_created",
            target_type="user",
            target_id=user.id,
            details={"source": "create_super_admin script"},
        )
        db.commit()
    print(
        f"Super Admin created for {email}. Sign in at the admin panel with this email, the "
        "password and the code we email."
    )


if __name__ == "__main__":
    main()
