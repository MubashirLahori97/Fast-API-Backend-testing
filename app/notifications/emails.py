"""Emails for notifications and policy updates. They never contain health information or a
family member's name (stories 12.1 and 12.2): the details are shown once the client opens the
app."""

from app.core.email import EmailMessage


def for_notification(to: str, subject: str, text: str) -> EmailMessage:
    """The email copy of a notification: its push and email text (`notifications.outside_text`)
    and, for kinds that have no text of their own, the general message as the subject."""
    return EmailMessage(
        to=to,
        subject=subject,
        body=f"{text}\n\nOpen Your Oracle to see the details.",
    )


def policy_updated(to: str, policy_name: str) -> EmailMessage:
    """Story 12.2, sent to every client when a new version is published."""
    return EmailMessage(
        to=to,
        subject=f"We’ve updated our {policy_name}",
        body=(
            f"We’ve updated our {policy_name}. You’ll be asked to review and accept it the next "
            "time you open Your Oracle."
        ),
    )


def teen_invite(to: str, link: str) -> EmailMessage:
    """Story 1.5's invite email, for Phase 3b. The link carries the invite token after `#`, like
    reset links, so it never reaches a server log."""
    return EmailMessage(
        to=to,
        subject="You’ve been invited to join Your Oracle",
        body=(
            "You’ve been invited to create your own Your Oracle account as part of a Family Plan. "
            "Set up your account to start using Oracle.\n\n"
            f"Finish Sign Up: {link}"
        ),
    )
