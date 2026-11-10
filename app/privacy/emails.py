"""Emails for Privacy & Data (story 11.4) and the support team's deletion list (Super Admin
5.2). None of them holds a name or health information: the team's email names only the
request's type, id and dates. Texts the stories don't give are listed in
docs/decisions/deletion-flow-1922.md."""

from datetime import UTC

from app.accounts.models import DeletionRequest
from app.core.email import EmailMessage

# The team's names for each type (Super Admin 5.2).
KIND_LABELS = {
    "family_member": "Family Member Deletion",
    "account": "Account Deletion",
    "teen_removal": "Invited Teen Removal",
    "teen": "Teen Deletion",
}
_QUESTIONS = "\n\nIf you have any questions, please contact the support team."


def acknowledgement(to: str, date: str) -> EmailMessage:
    """Story 11.4's acknowledgement email, sent directly when the deletion_acknowledged notice
    (whose email copy has the same text) can't go."""
    return EmailMessage(
        to=to,
        subject="Deletion requested",
        body=(
            "We’ve received your request to delete your account. You can keep using Your Oracle "
            f"and download your information until {date}. After that, your account will be "
            "deleted."
        ),
    )


def teen_deletion_notice(to: str, date: str) -> EmailMessage:
    """Story 12.1's teen deletion notice, sent directly when the notice can't go."""
    return EmailMessage(
        to=to,
        subject="Your account",
        body=(
            f"Your account and information will be deleted on {date}. You can keep using Your "
            "Oracle and download your information until then."
        ),
    )


def by_email_acknowledgement(to: str, due: str) -> EmailMessage:
    """Super Admin 5.2: a teen who emailed the team "is acknowledged by email". No grace
    period, so it gives the deadline."""
    return EmailMessage(
        to=to,
        subject="We’ve received your deletion request",
        body=(
            "We’ve received your request to delete your Your Oracle account and information. "
            f"We’ll complete it by {due}, and email you when it’s done." + _QUESTIONS
        ),
    )


def deletion_complete(to: str, deletion_request: DeletionRequest) -> EmailMessage:
    """Story 11.4 and Super Admin 5.2: the client, and any teen affected, is emailed once the
    deletion is complete. A family member's deletion is told in the app instead (8.2)."""
    if deletion_request.kind == "account":
        what = (
            "Your Your Oracle account has been permanently deleted, as you asked, with your "
            "information and the information of everyone on your account."
        )
    else:
        what = "Your Your Oracle account and its information have been permanently deleted."
    return EmailMessage(to=to, subject="Your deletion is complete", body=what + _QUESTIONS)


def teen_deleted_with_parent(to: str) -> EmailMessage:
    """Story 11.4's "Deletion complete (sent to an invited teen)"."""
    return EmailMessage(
        to=to,
        subject="Your account has been deleted",
        body=(
            "Your account has been deleted because your parent or guardian deleted their "
            "account. To keep using Your Oracle, a parent or guardian will need to sign up "
            "again and add you."
        ),
    )


def teen_removal_complete(to: str) -> EmailMessage:
    """Super Admin 5.2's "the Client ... is emailed" for an Invited Teen Removal: the parent who
    removed the teen. No name."""
    return EmailMessage(
        to=to,
        subject="Your deletion is complete",
        body=(
            "The account and information of the teen you removed from your family have been "
            "permanently deleted." + _QUESTIONS
        ),
    )


def legal_hold(to: str) -> EmailMessage:
    """Super Admin 5.2: "The status shows On legal hold, and the deletion waits. The Client is
    told by email." It doesn't say what the hold is about."""
    return EmailMessage(
        to=to,
        subject="An update on your deletion request",
        body=(
            "We can’t complete your deletion request yet, because we’re required to keep some "
            "information for now. We’ll complete it as soon as we can, and email you when it’s "
            "done." + _QUESTIONS
        ),
    )


def new_deletion_request(to: str, deletion_request: DeletionRequest) -> EmailMessage:
    """Super Admin 5.2: once the grace period ends, the request appears in the team's list as
    Pending review, and the team is notified."""
    label = KIND_LABELS[deletion_request.kind]
    received = deletion_request.requested_at.astimezone(UTC)
    due = deletion_request.due_at.astimezone(UTC)
    return EmailMessage(
        to=to,
        subject=f"Deletion request ready for review: {label}",
        body=(
            "A deletion request has finished its grace period and is ready for review.\n\n"
            f"Type: {label}\n"
            f"Request: {deletion_request.id}\n"
            f"Received: {received:%d %b %Y, %H:%M} UTC\n"
            f"Due by: {due:%d %b %Y} UTC\n\n"
            "Open Deletion Requests in the admin panel to review it. For privacy, this email "
            "doesn’t include the client’s details."
        ),
    )
