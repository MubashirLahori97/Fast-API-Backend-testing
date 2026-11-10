from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from app.core import audit
from app.core.audit import AuditEvent


def test_record_saves_an_event(db):
    event = audit.record(
        db,
        "auth.sign_in.failed",
        target_type="user",
        target_id="1234",
        details={"reason": "wrong_password"},
    )
    db.commit()

    saved = db.scalars(select(AuditEvent).where(AuditEvent.id == event.id)).one()
    assert saved.action == "auth.sign_in.failed"
    assert saved.target_id == "1234"
    assert saved.details == {"reason": "wrong_password"}
    assert saved.occurred_at is not None


def test_record_takes_ip_and_user_agent_from_the_request(db):
    request = Request(
        {"type": "http", "client": ("203.0.113.5", 51000), "headers": [(b"user-agent", b"iOS")]}
    )

    event = audit.record(db, "auth.sign_out", request=request)

    assert event.ip_address == "203.0.113.5"
    assert event.user_agent == "iOS"


def test_record_stores_an_ipv6_address_as_its_64_block(db):
    request = Request({"type": "http", "client": ("2001:db8:1:2:3:4:5:6", 51000), "headers": []})

    event = audit.record(db, "auth.sign_in.failed", request=request)

    assert event.ip_address == "2001:db8:1:2::/64"


# client_ip: the form the audit log stores and the per-IP limits count (security review)


def request_from(host: str) -> SimpleNamespace:
    """Stands in for a request: client_ip only reads .client.host."""
    return SimpleNamespace(client=SimpleNamespace(host=host))


@pytest.mark.parametrize(
    ("host", "stored"),
    [
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.5", "203.0.113.5"),
        ("203.0.113.5", "203.0.113.5"),
        ("testclient", "testclient"),
    ],
    ids=["ipv6", "ipv6-short-form", "ipv4-mapped-ipv6", "ipv4", "not-an-address"],
)
def test_client_ip(host, stored):
    assert audit.client_ip(request_from(host)) == stored


def test_client_ip_without_a_client_is_none():
    assert audit.client_ip(SimpleNamespace(client=None)) is None


def test_client_ip_without_a_request_is_none():
    assert audit.client_ip(None) is None


@pytest.mark.parametrize(
    "statement",
    [
        update(AuditEvent).values(action="changed"),
        delete(AuditEvent),
        text("TRUNCATE audit_events"),
    ],
    ids=["update", "delete", "truncate"],
)
def test_audit_events_cannot_be_changed_or_removed(db, statement):
    audit.record(db, "test.event")
    db.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(statement)
