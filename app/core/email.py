"""Sending email. Code depends on the EmailSender protocol; the real provider plugs in later."""

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Annotated, Protocol

from fastapi import BackgroundTasks, Depends

from app.core.config import settings


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Development only: prints emails to the terminal instead of sending them."""

    def send(self, message: EmailMessage) -> None:
        print(
            f"--- Email (not sent) ---\nFrom: {settings.email_from}\nTo: {message.to}\n"
            f"Subject: {message.subject}\n\n{message.body}\n------------------------",
            flush=True,
        )


class SmtpEmailSender:
    """Development only: hands each email to the local test inbox (Mailpit in compose.yaml),
    which keeps it at http://localhost:8025 instead of delivering it. Turned on with
    EMAIL_BACKEND=smtp."""

    def send(self, message: EmailMessage) -> None:
        email = MimeMessage()
        email["From"] = settings.email_from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.send_message(email)


class InMemoryEmailSender:
    """For tests: keeps sent emails in a list instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


def get_email_sender() -> EmailSender:
    """FastAPI dependency. Return the real provider here once one is chosen."""
    if settings.environment == "production":
        # The console sender would write codes and reset links into the server logs, and the
        # SMTP one only reaches the local test inbox.
        raise RuntimeError("No email provider is configured for production.")
    if settings.email_backend == "smtp":
        return SmtpEmailSender()
    return ConsoleEmailSender()


SendEmail = Callable[[EmailMessage], None]


def send_after_response(
    background: BackgroundTasks, sender: Annotated[EmailSender, Depends(get_email_sender)]
) -> SendEmail:
    """FastAPI dependency: emails go out after the response, so a slow or failing provider
    doesn't delay or break the request, and response times don't reveal whether an email
    was sent."""

    def send(message: EmailMessage) -> None:
        background.add_task(sender.send, message)

    return send


EmailLater = Annotated[SendEmail, Depends(send_after_response)]
