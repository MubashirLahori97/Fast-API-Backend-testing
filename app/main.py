from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.accounts.router import router as accounts_router
from app.admin.admins.router import router as admin_admins_router
from app.admin.audit.router import router as admin_audit_router
from app.admin.auth.router import router as admin_invitations_router
from app.admin.notifications.router import router as admin_notifications_router
from app.admin.operations import public_router as public_policies_router
from app.admin.operations import router as admin_operations_router
from app.admin.profile.router import router as admin_profile_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.billing.router import webhook_router as billing_webhook_router
from app.conversations.router import router as conversations_router
from app.core.config import settings
from app.core.database import DbSession
from app.core.errors import register_error_handlers
from app.dashboard.router import router as dashboard_router
from app.guidance.router import router as guidance_router
from app.health.router import router as health_router
from app.notifications.router import router as notifications_router
from app.privacy.router import router as privacy_router
from app.profiles.router import router as profiles_router
from app.support.router import router as support_router
from app.teens.router import router as teens_router
from app.visits.router import router as visits_router
from app.wellness.router import router as wellness_router


class NoStore:
    """Adds Cache-Control: no-store to every response: they carry tokens and health data, so
    browsers and proxies must not keep them. Plain ASGI rather than @app.middleware("http"),
    which wraps the whole response and gets in the way of streamed replies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_header)


show_docs = settings.environment != "production"
app = FastAPI(
    title="Genesis Health API",
    docs_url="/docs" if show_docs else None,
    redoc_url="/redoc" if show_docs else None,
    openapi_url="/openapi.json" if show_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(NoStore)
register_error_handlers(app)

# Every endpoint is under /api/v1, like the team's API. A version 2 that changes what an
# endpoint takes or returns would go under /api/v2, so older app versions keep working.
api = APIRouter(prefix="/api/v1")


@api.get("/health")
def health(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "database": "ok"}


api.include_router(auth_router)
api.include_router(accounts_router)
api.include_router(profiles_router)
api.include_router(health_router)
api.include_router(conversations_router)
api.include_router(guidance_router)
api.include_router(visits_router)
api.include_router(wellness_router)
api.include_router(support_router)
api.include_router(billing_router)
api.include_router(billing_webhook_router)
api.include_router(notifications_router)
api.include_router(privacy_router)
api.include_router(teens_router)
api.include_router(dashboard_router)
# The admin panel (Phase A part 1: sign-in setup, Admin Management, My Profile, Audit Logs,
# notifications).
api.include_router(admin_invitations_router)
api.include_router(admin_admins_router)
api.include_router(admin_profile_router)
api.include_router(admin_audit_router)
api.include_router(admin_notifications_router)
# Phase A part 2: Dashboard, clients, escalations, support and deletion requests, knowledge
# base, plans and policies; and the public policy texts (after accounts' /policies/current).
api.include_router(admin_operations_router)
api.include_router(public_policies_router)
app.include_router(api)
