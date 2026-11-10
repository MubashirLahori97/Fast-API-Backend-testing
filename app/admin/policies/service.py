"""Consent Management (Super Admin stories 9.1 and 9.2). Super Admin only: since the 6 Nov 19:22
stories, Admins can't access Consent Management (the router uses SuperAdminSession).

- The versions themselves are the accounts package's `policy_versions`; the texts, summaries
  and drafts are `policy_texts` (app/admin/policies/models.py).
- Publishing calls accounts.service.publish_policy_version, which makes the version live
  straight away, ends every client's signed-in sessions, emails every client and audits it,
  and then the team is notified. The draft becomes the version's text in the same commit, so a
  failed publish leaves the draft as it was.
- Every view of a policy or an earlier version, and every draft saved, is audited.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.accounts import service as accounts
from app.accounts.models import PolicyAcceptance, PolicyVersion
from app.admin.common import is_teen
from app.admin.notifications.service import notify_admins
from app.admin.policies.models import PolicyText
from app.admin.policies.schemas import (
    DraftOut,
    DraftSaved,
    PersonRef,
    PolicyDetail,
    PolicyKind,
    PolicyList,
    PolicyRow,
    PreviewOut,
    PublicPolicyOut,
    Published,
    VersionDetail,
    VersionRef,
)
from app.auth.models import User
from app.conversations.models import HealthConsent
from app.core import audit
from app.core.errors import AppError, database_errors_retryable

# Super Admin 9.1 and 9.2's messages.
PUBLISHED_READ_ONLY = "Published versions can’t be changed. Create a new version instead."
TEXT_EMPTY = "Please add the policy text."
SUMMARY_EMPTY = "Please add a short summary of what’s changed."
PUBLISH_CONFIRMATION = (
    "Publish version {version} of the {name}? Every Client will be asked to accept it before "
    "they can continue."
)
DRAFT_SAVED = "Your draft has been saved."
PUBLISHED = "Version {version} of the {name} is now live. Clients have been emailed."
PUBLISH_FAILED = "We couldn’t publish this version. Please try again."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
POLICY_NOT_FOUND = "We couldn’t find that policy."
VERSION_NOT_FOUND = "We couldn’t find that version."
NO_DRAFT = "There’s no draft of this policy. Please create a new version first."

POLICY_KINDS: tuple[PolicyKind, ...] = ("terms", "privacy", "health_consent")
# The stories' names, for a policy with no version yet.
DEFAULT_NAMES = {
    "terms": "Terms of Service",
    "privacy": "Privacy Policy",
    "health_consent": "Health Consent",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _check_kind(kind: str) -> None:
    if kind not in POLICY_KINDS:
        raise AppError(404, "policy_not_found", POLICY_NOT_FOUND)


def _live(db: Session, kind: str) -> PolicyVersion | None:
    found = accounts.current_policies(db, (kind,))
    return found[0] if found else None


def _name(live: PolicyVersion | None, kind: str) -> str:
    return live.title if live is not None else DEFAULT_NAMES[kind]


def _person(db: Session, user_id: uuid.UUID | None) -> PersonRef | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return PersonRef(id=user_id, first_name=user.first_name if user else None)


def _published_text(db: Session, kind: str, version: str) -> PolicyText | None:
    return db.scalar(
        select(PolicyText)
        .where(
            PolicyText.kind == kind, PolicyText.version == version, PolicyText.status == "published"
        )
        .options(undefer(PolicyText.text))
    )


def _draft(db: Session, kind: str, *, lock: bool = False) -> PolicyText | None:
    query = (
        select(PolicyText)
        .where(PolicyText.kind == kind, PolicyText.status == "draft")
        .options(undefer(PolicyText.text))
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def _acceptance(db: Session, live: PolicyVersion | None) -> tuple[int, int]:
    """Clients (adults with an active account; teens' parents accept for them) who have and
    haven't accepted the live version."""
    clients = select(User.id).where(User.role == "client", User.status == "active", ~is_teen())
    total = db.scalar(select(func.count()).select_from(clients.subquery()))
    if live is None:
        return 0, total
    if live.kind == "health_consent":
        accepted_by = select(HealthConsent.accepted_by_id).where(
            HealthConsent.policy_version_id == live.id
        )
    else:
        accepted_by = select(PolicyAcceptance.user_id).where(
            PolicyAcceptance.policy_version_id == live.id
        )
    accepted = db.scalar(
        select(func.count()).select_from(clients.where(User.id.in_(accepted_by)).subquery())
    )
    return accepted, total - accepted


def _version_ref(db: Session, policy: PolicyVersion) -> VersionRef:
    text = _published_text(db, policy.kind, policy.version)
    return VersionRef(
        id=policy.id,
        version=policy.version,
        title=policy.title,
        published_at=policy.published_at,
        published_by=_person(db, text.published_by_id) if text else None,
    )


def _version_detail(db: Session, policy: PolicyVersion) -> VersionDetail:
    text = _published_text(db, policy.kind, policy.version)
    return VersionDetail(
        **_version_ref(db, policy).model_dump(),
        kind=policy.kind,
        text=text.text if text else None,
        summary_of_changes=text.summary_of_changes if text else None,
        url=policy.url,
    )


def _draft_out(db: Session, draft: PolicyText) -> DraftOut:
    return DraftOut(
        version=draft.version,
        text=draft.text,
        summary_of_changes=draft.summary_of_changes,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        updated_by=_person(db, draft.updated_by_id),
    )


def _audit(db: Session, action: str, admin: User, request, *, kind: str, target_id=None, **more):
    audit.record(
        db,
        action,
        actor_id=admin.id,
        target_type="policy_version" if target_id else "policy",
        target_id=target_id,
        request=request,
        details={"kind": kind, **more},
    )


def list_policies(db: Session) -> PolicyList:
    """9.1's listing: each policy's live version, publish date, acceptance numbers, and whether
    a draft of the next version exists."""
    items = []
    for kind in POLICY_KINDS:
        live = _live(db, kind)
        accepted, not_accepted = _acceptance(db, live)
        items.append(
            PolicyRow(
                kind=kind,
                name=_name(live, kind),
                live_version=live.version if live else None,
                published_at=live.published_at if live else None,
                accepted=accepted,
                not_accepted=not_accepted,
                has_draft=_draft(db, kind) is not None,
            )
        )
    return PolicyList(items=items)


def _detail(db: Session, kind: str) -> PolicyDetail:
    live = _live(db, kind)
    earlier = db.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.kind == kind, PolicyVersion.published_at <= _now())
        .order_by(PolicyVersion.published_at.desc())
    ).all()
    draft = _draft(db, kind)
    accepted, not_accepted = _acceptance(db, live)
    return PolicyDetail(
        kind=kind,
        name=_name(live, kind),
        live=_version_detail(db, live) if live else None,
        history=[
            _version_ref(db, policy) for policy in earlier if live is None or policy.id != live.id
        ],
        draft=_draft_out(db, draft) if draft else None,
        accepted=accepted,
        not_accepted=not_accepted,
    )


def get_policy(db: Session, admin: User, kind: str, request: Request | None = None) -> PolicyDetail:
    """9.1's details: the live text, the version history and any draft. Audited."""
    _check_kind(kind)
    detail = _detail(db, kind)
    with database_errors_retryable(db):
        _audit(db, "policy.viewed", admin, request, kind=kind)
        db.commit()
    return detail


def get_version(
    db: Session, admin: User, kind: str, version_id: uuid.UUID, request: Request | None = None
) -> VersionDetail:
    """An earlier (or the live) version, read-only. Audited."""
    _check_kind(kind)
    policy = db.get(PolicyVersion, version_id)
    if policy is None or policy.kind != kind or policy.published_at > _now():
        raise AppError(404, "policy_version_not_found", VERSION_NOT_FOUND)
    detail = _version_detail(db, policy)
    with database_errors_retryable(db):
        _audit(db, "policy.version_viewed", admin, request, kind=kind, target_id=policy.id)
        db.commit()
    return detail


def refuse_published_edit() -> None:
    """9.1: published versions can't be edited."""
    raise AppError(409, "policy_version_published", PUBLISHED_READ_ONLY)


def next_version(db: Session, kind: str) -> str:
    """9.2's automatic version number: the newest version's last number plus one ("1.2" becomes
    "1.3"). A version that isn't numbers gets ".1" added."""
    versions = db.scalars(select(PolicyVersion.version).where(PolicyVersion.kind == kind)).all()
    if not versions:
        return "1.0"

    def key(version: str) -> tuple:
        parts = version.split(".")
        return tuple(int(part) for part in parts) if all(p.isdigit() for p in parts) else (-1,)

    newest = max(versions, key=key)
    parts = newest.split(".")
    if not all(part.isdigit() for part in parts):
        return f"{newest}.1"
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def create_draft(db: Session, admin: User, kind: str, request: Request | None = None) -> DraftSaved:
    """9.2's + New version: a draft filled in with the live version's text and the next version
    number. If a draft exists already, it's returned as it is."""
    _check_kind(kind)
    with database_errors_retryable(db):
        draft = _draft(db, kind)
        if draft is None:
            live = _live(db, kind)
            live_text = _published_text(db, kind, live.version) if live else None
            draft = PolicyText(
                kind=kind,
                version=next_version(db, kind),
                text=live_text.text if live_text else "",
                summary_of_changes="",
                status="draft",
                created_by_id=admin.id,
                updated_by_id=admin.id,
            )
            try:
                with db.begin_nested():
                    db.add(draft)
                    db.flush()
            except IntegrityError:  # another admin created it meanwhile
                draft = _draft(db, kind)
            else:
                _audit(db, "policy.draft_created", admin, request, kind=kind, version=draft.version)
        db.commit()
    return DraftSaved(draft=_draft_out(db, draft), message=DRAFT_SAVED)


def save_draft(
    db: Session,
    admin: User,
    kind: str,
    text: str | None,
    summary: str | None,
    sent: set[str],
    request: Request | None = None,
) -> DraftSaved:
    """9.2's Save as draft: clients don't see it."""
    _check_kind(kind)
    with database_errors_retryable(db):
        draft = _draft(db, kind, lock=True)
        if draft is None:
            raise AppError(404, "no_draft", NO_DRAFT)
        if "text" in sent:
            draft.text = text or ""
        if "summary_of_changes" in sent:
            draft.summary_of_changes = summary or ""
        draft.updated_by_id = admin.id
        draft.updated_at = _now()
        _audit(db, "policy.draft_saved", admin, request, kind=kind, version=draft.version)
        db.commit()
    return DraftSaved(draft=_draft_out(db, draft), message=DRAFT_SAVED)


def preview(db: Session, kind: str) -> PreviewOut:
    _check_kind(kind)
    draft = _draft(db, kind)
    if draft is None:
        raise AppError(404, "no_draft", NO_DRAFT)
    name = _name(_live(db, kind), kind)
    version = next_version(db, kind)
    return PreviewOut(
        kind=kind,
        name=name,
        version=version,
        summary_of_changes=draft.summary_of_changes,
        text=draft.text,
        publish_confirmation=PUBLISH_CONFIRMATION.format(version=version, name=name),
    )


def publish(
    db: Session, admin: User, kind: str, confirmed: bool, request: Request | None = None
) -> Published:
    """9.2's Publish, with `confirmed` (409 with the story's confirmation otherwise). The text
    and summary of changes must be filled in."""
    _check_kind(kind)
    with database_errors_retryable(db):
        draft = _draft(db, kind, lock=True)
    if draft is None:
        raise AppError(404, "no_draft", NO_DRAFT)
    if not draft.text.strip():
        raise AppError(422, "policy_text_required", TEXT_EMPTY, "text")
    if not draft.summary_of_changes.strip():
        raise AppError(422, "summary_required", SUMMARY_EMPTY, "summary_of_changes")
    live = _live(db, kind)
    name = _name(live, kind)
    version = next_version(db, kind)
    if not confirmed:
        db.rollback()
        raise AppError(
            409,
            "confirmation_required",
            PUBLISH_CONFIRMATION.format(version=version, name=name),
        )
    now = _now()
    draft.version = version
    draft.status = "published"
    draft.published_at = now
    draft.published_by_id = admin.id
    try:
        # Commits the draft's change with the new version, or rolls both back.
        policy = accounts.publish_policy_version(
            db, kind, version, name, None, now, actor_id=admin.id, request=request
        )
    except AppError as error:
        if error.code == "save_failed":
            raise AppError(503, "publish_failed", PUBLISH_FAILED) from None
        raise
    with database_errors_retryable(db):
        notify_admins(db, "policy_published", {"policy": kind}, target_id=policy.id)
        db.commit()
    return Published(policy=_detail(db, kind), message=PUBLISHED.format(version=version, name=name))


def public_policy(db: Session, policy_version_id: uuid.UUID) -> PublicPolicyOut:
    """A published version's text, for the apps (the policies are public)."""
    policy = db.get(PolicyVersion, policy_version_id)
    if policy is None or policy.published_at > _now():
        raise AppError(404, "policy_version_not_found", VERSION_NOT_FOUND)
    text = _published_text(db, policy.kind, policy.version)
    return PublicPolicyOut(
        id=policy.id,
        kind=policy.kind,
        version=policy.version,
        title=policy.title,
        text=text.text if text else None,
        summary_of_changes=text.summary_of_changes if text else None,
        url=policy.url,
        published_at=policy.published_at,
    )
