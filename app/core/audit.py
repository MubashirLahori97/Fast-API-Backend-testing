"""Append-only audit log. The BAA (Section 13) requires auth and account events to be kept 6+ years.

Never put health data, passwords, codes or tokens in an event: events outlive account deletions.
The database refuses UPDATE and DELETE on this table (see the first migration).
"""

import ipaddress
import uuid
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    # The sign-in limits count recent events per IP address and per account.
    __table_args__ = (
        Index("ix_audit_events_ip_action_time", "ip_address", "action", "occurred_at"),
        Index("ix_audit_events_actor_action_time", "actor_id", "action", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    action: Mapped[str] = mapped_column(index=True)  # e.g. "auth.sign_in.failed"
    # Plain ids with no foreign keys, so events survive when the user or record is deleted.
    actor_id: Mapped[uuid.UUID | None]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


def client_ip(request: Request | None) -> str | None:
    """The client's address, as the audit log stores it and the per-IP limits count it. An
    IPv6 address is cut to its /64, the block one home or phone connection usually gets, so
    moving around inside it doesn't escape the limits."""
    if request is None or request.client is None:
        return None
    host = request.client.host
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host  # not an address, e.g. the test client's "testclient"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the session. It's saved when the caller commits."""
    event = AuditEvent(
        action=action,
        actor_id=actor_id,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent") if request else None,
        details=details or {},
    )
    db.add(event)
    return event
