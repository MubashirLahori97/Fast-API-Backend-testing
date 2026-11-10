import pytest

from app.core.config import settings
from app.core.email import get_email_sender


def test_console_email_is_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(RuntimeError):
        get_email_sender()


def test_responses_are_not_cached(client):
    assert client.get("/health").headers["cache-control"] == "no-store"
