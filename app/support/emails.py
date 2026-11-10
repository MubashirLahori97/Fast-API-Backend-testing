"""The email that tells the support team about a new request. Like every admin notification
(Super Admin story 11.1), it holds no health information and no client details: only the
type and the request's id. The team reads the request in the admin panel."""

from datetime import UTC

from app.core.email import EmailMessage
from app.support.models import SupportRequest

# The admin panel's names for each type (Super Admin story 5.1).
KIND_LABELS = {
    "talk_to_support": "Talk to Support Team",
    "consultation": "Consultation Request",
    "knowledge_gap": "Knowledge Gap",
    "email_change": "Email Change Request",
}


def new_request(to: str, support_request: SupportRequest) -> EmailMessage:
    label = KIND_LABELS[support_request.kind]
    return EmailMessage(
        to=to,
        subject=f"New support request: {label}",
        body=(
            "You have a new support request to review.\n\n"
            f"Type: {label}\n"
            f"Request: {support_request.id}\n"
            f"Received: {support_request.created_at.astimezone(UTC):%d %b %Y, %H:%M} UTC\n\n"
            "Open Support Requests in the admin panel to read it. For privacy, this email "
            "doesn’t include the client’s details or their message."
        ),
    )
