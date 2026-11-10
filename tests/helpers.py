import re

from app.core.email import InMemoryEmailSender

PASSWORD = "Healing!2026"

# Story wording shared by several test files. Written out here, not imported from the app, so
# a test fails if the app's wording drifts from the stories.
PASSWORD_RULES = (
    "Your password needs at least 8 characters, including an uppercase letter, a lowercase "
    "letter, a number and a special character."
)
PASSWORDS_DONT_MATCH = "The passwords don’t match."


def last_code(email_sender: InMemoryEmailSender) -> str:
    """The 6-digit code in the most recent email."""
    match = re.search(r"\b(\d{6})\b", email_sender.sent[-1].body)
    assert match, "the last email has no verification code"
    return match.group(1)


def last_reset_token(email_sender: InMemoryEmailSender) -> str:
    """The token in the most recent password reset link."""
    match = re.search(r"token=([\w-]+)", email_sender.sent[-1].body)
    assert match, "the last email has no reset link"
    return match.group(1)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
