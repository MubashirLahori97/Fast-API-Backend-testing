import uuid

from fastapi import APIRouter, Request

from app.admin.dependencies import SuperAdminSession
from app.admin.policies import service
from app.admin.policies.schemas import (
    DraftBody,
    DraftSaved,
    PolicyDetail,
    PolicyKind,
    PolicyList,
    PreviewOut,
    PublicPolicyOut,
    PublishBody,
    Published,
    VersionDetail,
)
from app.core.database import DbSession

# Super Admin only: Admins can't access Consent Management (9.1 and 9.2, 6 Nov 19:22). An
# Admin gets 403 `super_admin_only`, a client 404.
router = APIRouter(prefix="/admin/policies", tags=["admin: policies"])
# The apps read a published version's text here, without signing in.
public_router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("")
def list_policies(session: SuperAdminSession, db: DbSession) -> PolicyList:
    """9.1's listing: each policy's live version and publish date, how many Clients have and
    haven't accepted it, and whether a draft exists."""
    return service.list_policies(db)


@router.get("/{kind}")
def get_policy(
    kind: PolicyKind, session: SuperAdminSession, request: Request, db: DbSession
) -> PolicyDetail:
    """9.1's details: the live text, the version history and any draft. Audited."""
    return service.get_policy(db, session.user, kind, request)


@router.get("/{kind}/versions/{version_id}")
def get_version(
    kind: PolicyKind,
    version_id: uuid.UUID,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> VersionDetail:
    """A published version, read-only. Audited."""
    return service.get_version(db, session.user, kind, version_id, request)


@router.put("/{kind}/versions/{version_id}")
def edit_published_version(
    kind: PolicyKind, version_id: uuid.UUID, session: SuperAdminSession
) -> None:
    """Published versions can't be changed (409): create a new version instead."""
    service.refuse_published_edit()


@router.post("/{kind}/draft")
def create_draft(
    kind: PolicyKind, session: SuperAdminSession, request: Request, db: DbSession
) -> DraftSaved:
    """9.2's + New version: a draft with the live text and the next version number (or the
    draft that already exists)."""
    return service.create_draft(db, session.user, kind, request)


@router.put("/{kind}/draft")
def save_draft(
    kind: PolicyKind,
    body: DraftBody,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> DraftSaved:
    """Save as draft: the policy text and the summary of changes."""
    return service.save_draft(
        db,
        session.user,
        kind,
        body.text,
        body.summary_of_changes,
        body.model_fields_set,
        request,
    )


@router.get("/{kind}/draft/preview")
def preview(kind: PolicyKind, session: SuperAdminSession, db: DbSession) -> PreviewOut:
    """9.2's Preview: the version as Clients will see it, and the publish confirmation."""
    return service.preview(db, kind)


@router.post("/{kind}/draft/publish")
def publish(
    kind: PolicyKind,
    body: PublishBody,
    session: SuperAdminSession,
    request: Request,
    db: DbSession,
) -> Published:
    """9.2's Publish, with confirmed: true: live straight away, every Client is emailed and
    signed out, and must accept it before continuing."""
    return service.publish(db, session.user, kind, body.confirmed, request)


@public_router.get("/{policy_version_id}")
def public_policy(policy_version_id: uuid.UUID, db: DbSession) -> PublicPolicyOut:
    """A published version's text and summary of changes, for the Terms, Privacy Policy, Health
    Consent and Policy Update screens (story 12.2), so policy text changes need no app
    release."""
    return service.public_policy(db, policy_version_id)
