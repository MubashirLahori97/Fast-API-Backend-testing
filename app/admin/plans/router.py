import uuid

from fastapi import APIRouter, Request

from app.admin.dependencies import SuperAdminSession
from app.admin.plans import service
from app.admin.plans.schemas import (
    PlanDetail,
    PlanEdit,
    PlanList,
    PlanNew,
    PlanSaved,
    PublishBody,
)
from app.core.database import DbSession

# Super Admin only (8.1 and 8.2): Admins get 403 super_admin_only, clients the usual 404.
router = APIRouter(prefix="/admin/plans", tags=["admin: plans and pricing"])


@router.get("")
def list_plans(session: SuperAdminSession, db: DbSession) -> PlanList:
    """8.1's listing: each plan's name, type, price (or trial length), family members and
    add-on price, status and the number of Clients on it."""
    return service.list_plans(db, session.user)


@router.post("", status_code=201)
def create_plan(
    body: PlanNew, session: SuperAdminSession, request: Request, db: DbSession
) -> PlanSaved:
    """8.2's + Add plan: action "draft", or "publish" with confirmed: true."""
    return service.create_plan(db, session.user, body, request)


@router.get("/{plan_id}")
def get_plan(plan_id: uuid.UUID, session: SuperAdminSession, db: DbSession) -> PlanDetail:
    """8.1's details: what's included and the price history."""
    return service.get_plan(db, session.user, plan_id)


@router.patch("/{plan_id}")
def update_plan(
    plan_id: uuid.UUID,
    body: PlanEdit,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> PlanSaved:
    """8.1's Edit, and setting a plan Active or Inactive. A price change or Inactive needs
    confirmed: true; without it the answer is 409 confirmation_required with the story's
    confirmation text."""
    return service.update_plan(db, session.user, plan_id, body, request)


@router.post("/{plan_id}/publish")
def publish_plan(
    plan_id: uuid.UUID,
    body: PublishBody,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> PlanSaved:
    """8.2's Publish for a draft plan, with confirmed: true."""
    return service.publish_plan(
        db, session.user, plan_id, confirmed=body.confirmed, request=request
    )
