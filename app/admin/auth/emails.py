"""Emails to Admins and the Super Admin about their own account. They never contain Client
information (Super Admin 7.2 and 12.2). Links carry their token after `#`, so it never reaches
a server log or a Referer header; the admin panel reads it from `location.hash`."""

from app.core.config import settings
from app.core.email import EmailMessage


def invite(to: str, first_name: str, token: str) -> EmailMessage:
    """Super Admin 7.2 and Admin 1.1: the invite with its Set up your account link."""
    return EmailMessage(
        to=to,
        subject="You’re invited to the Your Oracle admin panel",
        body=(
            f"Hi {first_name},\n\n"
            "You’ve been invited to join the Your Oracle admin panel as an Admin.\n\n"
            f"Set up your account: {settings.admin_invite_url}#token={token}\n\n"
            f"The link works once and expires in {settings.admin_invite_hours} hours. If it has "
            "expired, ask the Super Admin to send a new one."
        ),
    )


def setup_code(to: str, code: str) -> EmailMessage:
    """Admin 1.1: the code that confirms the email address during setup."""
    return EmailMessage(
        to=to,
        subject="Your verification code",
        body=(
            f"Your verification code for the Your Oracle admin panel is {code}.\n\n"
            f"It expires in {settings.code_ttl_minutes} minutes. If you didn’t set up an admin "
            "account, you can ignore this email."
        ),
    )


def sign_in_code(to: str, code: str) -> EmailMessage:
    """Super Admin 1.1 and Admin 1.2: the code needed at every sign-in."""
    return EmailMessage(
        to=to,
        subject="Your verification code",
        body=(
            f"Your verification code for the Your Oracle admin panel is {code}.\n\n"
            f"It expires in {settings.code_ttl_minutes} minutes. Someone has just signed in to "
            "your admin account with your password. If this wasn’t you, reset your password "
            "straight away and tell the Super Admin."
        ),
    )


def password_reset(to: str, token: str) -> EmailMessage:
    """Super Admin 1.2 and Admin 1.3."""
    return EmailMessage(
        to=to,
        subject="Reset your password",
        body=(
            "We received a request to reset your password for the Your Oracle admin panel.\n\n"
            f"Reset it here: {settings.admin_password_reset_url}#token={token}\n\n"
            f"The link works once and expires in {settings.reset_link_ttl_minutes} minutes. "
            "If you didn’t ask for this, you can ignore this email."
        ),
    )


def password_changed(to: str) -> EmailMessage:
    """Super Admin 1.2 and 12.2, Admin 1.3: the confirmation after a reset or a change."""
    return EmailMessage(
        to=to,
        subject="Your password was changed",
        body=(
            "Your password for the Your Oracle admin panel has just been changed.\n\n"
            "If this wasn’t you, reset your password straight away and tell the Super Admin."
        ),
    )
