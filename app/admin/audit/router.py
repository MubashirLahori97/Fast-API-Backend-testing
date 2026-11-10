from fastapi import APIRouter, Request, Response

from app.admin.audit import service
from app.admin.audit.schemas import AuditFilterOptions, AuditFilters, AuditPage, AuditSearch
from app.admin.dependencies import SuperAdminSession
from app.core.database import DbSession

# Super Admin only: Admins can't access Audit Logs (10.1, 6 Nov 19:22); their actions are still
# recorded. An Admin gets 403 `super_admin_only`, a client 404. The filters are POSTed so a
# searched name or email stays out of URLs and logs.
router = APIRouter(prefix="/admin/audit-logs", tags=["admin: audit logs"])


@router.get("/filters")
def filter_options(session: SuperAdminSession) -> AuditFilterOptions:
    """The categories (10.1's groups) and roles the filters offer."""
    return service.filter_options(session.user)


@router.post("/search")
def search_audit_logs(data: AuditSearch, session: SuperAdminSession, db: DbSession) -> AuditPage:
    """Story 10.1's Audit Log screen, newest first, searched by name or email and filtered by
    date range, role and category."""
    return service.search(db, session.user, data)


@router.post("/export")
def export_audit_logs(
    data: AuditFilters, session: SuperAdminSession, request: Request, db: DbSession
) -> Response:
    """Export: the filtered entries as a CSV file. The export is recorded in the audit log.
    422 `export_too_large` asks for a shorter date range."""
    content = service.export(db, session.user, data, request)
    filename = service.export_filename()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
