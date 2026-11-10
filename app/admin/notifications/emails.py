"""The email copy of an admin notification (Super Admin 11.1). It says only the kind's general
text, never health information or Client names: the details are in the admin panel."""

from app.core.config import settings
from app.core.email import EmailMessage


def for_notification(to: str, title: str, text: str, *, can_turn_off: bool) -> EmailMessage:
    footer = "For privacy, this email doesn’t include any client details."
    if can_turn_off:
        footer += " You can turn these emails on or off in Notification Preferences."
    return EmailMessage(
        to=to,
        subject=title,
        body=(
            f"{text}.\n\n"
            f"Open the Your Oracle admin panel to see the details: {settings.admin_panel_url}\n\n"
            f"{footer}"
        ),
    )
