"""Emails sent by the sign-in flows. They never contain health information."""

from app.core.config import settings
from app.core.email import EmailMessage


def verification_code(to: str, code: str, purpose: str) -> EmailMessage:
    if purpose == "sign_in":
        # A sign-in code means someone used the right password, so say so.
        note = (
            "Someone just signed in to your account with your password from a new device. "
            "If this wasn’t you, reset your password straight away."
        )
    else:
        note = "If you didn’t create an account, you can ignore this email."
    return EmailMessage(
        to=to,
        subject="Your verification code",
        body=(
            f"Your verification code for Your Oracle is {code}.\n\n"
            f"It expires in {settings.code_ttl_minutes} minutes. {note}"
        ),
    )


def account_created(to: str) -> EmailMessage:
    """Sent when a sign-up's code is verified. If someone else verified it, the owner can take
    the account back with Forgot password."""
    return EmailMessage(
        to=to,
        subject="Welcome to Your Oracle",
        body=(
            "An account with Your Oracle has just been created with this email address.\n\n"
            "If this wasn’t you, reset your password straight away from the sign-in screen "
            "(Forgot password), or contact the support team."
        ),
    )


def password_reset(to: str, token: str) -> EmailMessage:
    # The token goes in the URL fragment (after #), which browsers don't send to servers
    # or put in Referer headers.
    return EmailMessage(
        to=to,
        subject="Reset your password",
        body=(
            "We received a request to reset your password for Your Oracle.\n\n"
            f"Reset it here: {settings.password_reset_url}#token={token}\n\n"
            f"The link works once and expires in {settings.reset_link_ttl_minutes} minutes. "
            "If you didn’t ask for this, you can ignore this email."
        ),
    )


def password_changed(to: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Your password was changed",
        body=(
            "Your password for Your Oracle has just been changed.\n\n"
            "If this wasn’t you, reset your password straight away or contact the support team."
        ),
    )
