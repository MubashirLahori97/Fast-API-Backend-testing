"""Passwords, tokens and codes. Nothing secret is stored in plain text."""

import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()  # Argon2id
# Checked when an email isn't registered, so a failed sign-in takes as long either way.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

PASSWORD_MAX_LENGTH = 128


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Returns (matches, upgraded_hash). upgraded_hash is set when the stored hash uses older
    settings and should be replaced. Pass None as the hash when there's no user."""
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False, None
    return _hasher.verify_and_update(password, password_hash)


def meets_password_rules(password: str) -> bool:
    """Sign-up rules (story 1.1): 8+ characters, with uppercase, lowercase, a number and a
    special character."""
    return (
        8 <= len(password) <= PASSWORD_MAX_LENGTH
        and re.search(r"[A-Z]", password) is not None
        and re.search(r"[a-z]", password) is not None
        and re.search(r"\d", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )


def new_token() -> str:
    """A random token for sessions, trusted devices and reset links."""
    return secrets.token_urlsafe(32)


def new_code() -> str:
    """A random 6-digit verification code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str) -> str:
    """SHA-256 of a token or code. Tokens are random enough that a slow hash isn't needed."""
    return hashlib.sha256(value.encode()).hexdigest()


def secret_matches(value: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(value), expected_hash)
