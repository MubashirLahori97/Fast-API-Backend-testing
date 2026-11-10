"""Support Request Management (Super Admin and Admin story 5.1).

The listing, details (audited), notes, resolve and reopen are the support package's own team
functions; this adds the stories' empty-list message and the Change email address
confirmation, and changes the email through accounts.service.change_email, which signs the
client out everywhere, clears trusted devices, tells both addresses and resolves the request.
"""

import uuid
from datetime import date, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.admin.common import day_range
from app.admin.support.schemas import AdminSupportRequestDetail, SupportRequestList
from app.auth.models import User
from app.core.email import SendEmail
from app.core.errors import AppError
from app.support import service as support
from app.support.models import SupportRequest
from app.support.schemas import AccountType, Kind, Status

# Super Admin and Admin 5.1 and 3.1's messages.
NO_REQUESTS = "There are no support requests right now."
CHANGE_EMAIL_CONFIRMATION = (
    "Change {name}’s email address to {email}? They’ll be signed out and asked to verify their "
    "new address."
)
EMAIL_CHANGED = "{name}’s email address has been changed."
EMAIL_IN_USE = "An account with this email address already exists."


def list_requests(
    db: Session,
    admin: User,
    *,
    kind: Kind | None,
    status: Status | None,
    account_type: AccountType | None,
    search: str | None,
    received_from: date | None,
    received_to: date | None,
    limit: int,
    offset: int,
) -> SupportRequestList:
    start, end = day_range(received_from, received_to)
    page = support.list_requests(
        db,
        admin,
        kind=kind,
        status=status,
        account_type=account_type,
        search=search,
        received_from=start,
        # list_requests includes its end; ours is the start of the next day.
        received_to=end - timedelta(microseconds=1) if end is not None else None,
        limit=limit,
        offset=offset,
    )
    return SupportRequestList(
        items=page.items, total=page.total, message=None if page.items else NO_REQUESTS
    )


def get_request(
    db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None
) -> AdminSupportRequestDetail:
    detail = support.get_request(db, admin, request_id, request)
    confirmation = None
    if detail.kind == "email_change" and detail.status == "open":
        confirmation = CHANGE_EMAIL_CONFIRMATION.format(
            name=detail.client.first_name, email=detail.requested_email
        )
    return AdminSupportRequestDetail(**detail.model_dump(), change_email_confirmation=confirmation)


def change_email(
    db: Session,
    admin: User,
    request_id: uuid.UUID,
    send: SendEmail,
    request: Request | None = None,
) -> str:
    """3.1 and 5.1's Change email address, from an open Email Change Request. An address
    another account has taken meanwhile isn't changed (409); the team contacts the client."""
    support_request = db.get(SupportRequest, request_id)
    if support_request is None or support_request.kind != "email_change":
        raise AppError(404, "support_request_not_found", support.REQUEST_NOT_FOUND)
    name = support_request.account.first_name
    try:
        accounts.change_email(db, admin, request_id, send, request)
    except AppError as error:
        if error.code == "email_taken":
            raise AppError(409, "email_taken", EMAIL_IN_USE) from None
        raise
    return EMAIL_CHANGED.format(name=name)
