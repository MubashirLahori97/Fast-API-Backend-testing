"""Emails about the account itself (story 11.1). They never contain health information.
The texts aren't in the stories (docs/decisions/phase-10-account.md)."""

from app.core.email import EmailMessage


def email_changed_old_address(to: str) -> EmailMessage:
    """Story 11.1: the confirmation at the old address. It doesn't name the new one, in case
    this address is no longer the client's."""
    return EmailMessage(
        to=to,
        subject="Your email address was changed",
        body=(
            "The email address for your Your Oracle account has just been changed, as you "
            "asked. From now on, please sign in with your new email address.\n\n"
            "If you didn’t ask for this, please contact the support team straight away."
        ),
    )


def email_changed_new_address(to: str) -> EmailMessage:
    """Story 11.1: the confirmation at the new address, when the in-app notice can't send its
    own email copy (notifications have stopped, for example while consent is revoked)."""
    return EmailMessage(
        to=to,
        subject="Your email address was changed",
        body=(
            f"Your email address has been changed to {to}. Please sign in again with your new "
            "email address. We’ll send you a verification code to confirm it’s you."
        ),
    )
