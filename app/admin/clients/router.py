import uuid
from datetime import date

from fastapi import APIRouter, Request

from app.admin.clients import service
from app.admin.clients.schemas import (
    AccountType,
    ClientActionOut,
    ClientDetail,
    ClientPage,
    ClientPlan,
    ClientStatus,
    DeactivateBody,
)
from app.admin.common import Limit, Offset
from app.admin.dependencies import AdminSession
from app.core.database import DbSession

router = APIRouter(prefix="/admin/clients", tags=["admin: clients"])


@router.get("", response_model_exclude_none=True)
def list_clients(
    session: AdminSession,
    db: DbSession,
    search: str | None = None,
    account_type: AccountType | None = None,
    plan: ClientPlan | None = None,
    status: ClientStatus | None = None,
    state: str | None = None,
    signed_up_from: date | None = None,
    signed_up_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ClientPage:
    """Super Admin and Admin 3.1: client accounts, newest first. Search by first name or email;
    filter by account type, status, state and sign-up date, and (Super Admin only) plan."""
    return service.list_clients(
        db,
        session.user,
        search=search,
        account_type=account_type,
        plan=plan,
        status=status,
        state=state,
        signed_up_from=signed_up_from,
        signed_up_to=signed_up_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{account_id}", response_model_exclude_none=True)
def client_detail(
    account_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> ClientDetail:
    """3.1's Client Details: account, consent, family members, teen link, activity, the
    health profile (read-only) and the actions, plus the subscription for the Super Admin. No
    conversations, guidance summaries, provider notes or visit logs. Audited."""
    return service.client_detail(db, session.user, account_id, request)


@router.post("/{account_id}/deactivate")
def deactivate(
    account_id: uuid.UUID,
    body: DeactivateBody,
    session: AdminSession,
    request: Request,
    db: DbSession,
) -> ClientActionOut:
    """3.2: signs the client out everywhere and stops them signing in, keeping everything.
    The reason is mandatory and recorded in the audit log."""
    return service.deactivate(db, session.user, account_id, body.reason, request)


@router.post("/{account_id}/reactivate")
def reactivate(
    account_id: uuid.UUID, session: AdminSession, request: Request, db: DbSession
) -> ClientActionOut:
    """3.2: the client can sign in again, with all their information intact."""
    return service.reactivate(db, session.user, account_id, request)
