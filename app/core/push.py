"""Sending push notifications. Code depends on the PushSender protocol; the real provider (FCM,
APNs or a service in front of them) plugs in later, like email.

A push never carries health details or names (story 12.1): the text is a general message, and
the data holds only the notification's id, so the app loads the rest once it's open.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import settings


@dataclass(frozen=True)
class PushMessage:
    token: str  # the device's push token, as the provider gave it to the app
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)


class InvalidPushToken(Exception):
    """The provider says this token no longer works: the app was uninstalled, or push was
    turned off in the phone's settings. The caller forgets the token."""


class PushSender(Protocol):
    def send(self, message: PushMessage) -> None:
        """Sends one push. Raises InvalidPushToken for a token that no longer works, and any
        other exception for a failure worth retrying."""
        ...


class ConsolePushSender:
    """Development only: prints pushes to the terminal instead of sending them."""

    def send(self, message: PushMessage) -> None:
        # Only the end of the token, which is enough to tell devices apart.
        print(
            f"--- Push (not sent) ---\nTo device: ...{message.token[-6:]}\n"
            f"{message.title}: {message.body}\nData: {message.data}\n-----------------------",
            flush=True,
        )


class InMemoryPushSender:
    """For tests: keeps sent pushes in a list. Tokens in `invalid` are refused as the provider
    would refuse an uninstalled app's token."""

    def __init__(self) -> None:
        self.sent: list[PushMessage] = []
        self.invalid: set[str] = set()

    def send(self, message: PushMessage) -> None:
        if message.token in self.invalid:
            raise InvalidPushToken
        self.sent.append(message)


def get_push_sender() -> PushSender:
    """The push sender. Return the real provider here once one is chosen (it needs a BAA only if
    it would see health data, which pushes never carry)."""
    if settings.environment == "production":
        # Refuse rather than quietly print device tokens into the server logs.
        raise RuntimeError("No push provider is configured for production.")
    return ConsolePushSender()
