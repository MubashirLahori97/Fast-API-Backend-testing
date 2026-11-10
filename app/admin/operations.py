"""The admin panel's operations (Phase A part 2), mounted together in app/main.py: Dashboard,
Client Management, Escalations, Support Requests, Deletion Requests, Knowledge Base, Plans and
Pricing, and Consent Management. Admin sign-in, Admin Management, the admin's own profile,
audit logs and admin notifications are mounted separately."""

from fastapi import APIRouter

from app.admin.clients.router import router as clients_router
from app.admin.dashboard.router import router as dashboard_router
from app.admin.deletions.router import router as deletions_router
from app.admin.escalations.router import router as escalations_router
from app.admin.knowledge.router import router as knowledge_router
from app.admin.plans.router import router as plans_router
from app.admin.policies.router import public_router as public_policies_router
from app.admin.policies.router import router as policies_router
from app.admin.support.router import router as support_router

router = APIRouter()
for part in (
    dashboard_router,
    clients_router,
    escalations_router,
    support_router,
    deletions_router,
    knowledge_router,
    plans_router,
    policies_router,
):
    router.include_router(part)

# GET /policies/{policy_version_id}: mount after the accounts router, whose /policies/current
# must match first.
public_router = public_policies_router
