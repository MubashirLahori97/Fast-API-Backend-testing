"""Client Management (Super Admin and Admin stories 3.1 and 3.2).

- The listing and Client Details show client accounts only (`role = client`); an Admin's or the
  Super Admin's id gets the same 404 as an unknown one.
- Every view of Client Details is audited (`admin.client_viewed`); loading the listing isn't.
- Deactivating sets `users.status` to `deactivated` and ends every session with
  `revoked_reason = account_deactivated`, so the client sees story 1.2's "Your account has been
  deactivated..." on their next request and at sign-in (app/auth/). Nothing is deleted, the
  subscription isn't touched, and a pending deletion carries on. Notifications stop because
  `notifications.service.notify` skips deactivated accounts. Reactivating sets it back; the
  client signs in again.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import case, exists, func, literal, null, or_, select, update
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.accounts.models import (
    OPEN_DELETION_STATUSES,
    ConsentRevocation,
    DeletionRequest,
    PolicyAcceptance,
    PolicyVersion,
)
from app.accounts.service import STATE_NAMES
from app.admin.clients.health import health_profile
from app.admin.clients.schemas import (
    AcceptedPolicyOut,
    AccountOut,
    AccountType,
    ActivityOut,
    ClientActionOut,
    ClientDetail,
    ClientPage,
    ClientPlan,
    ClientRow,
    ClientStatus,
    ConfirmationsOut,
    ConsentOut,
    FamilyMemberOut,
    InvitedTeenOut,
    OpenDeletionRequest,
    OpenEscalation,
    OpenSupportRequest,
    SubscriptionOut,
    TeenLinkOut,
)
from app.admin.common import day_range, is_teen, like, subscription_gives_access
from app.auth.models import User, UserSession
from app.billing import entitlements
from app.billing.models import Subscription
from app.conversations.models import Conversation, Escalation, HealthConsent
from app.core import audit
from app.core.ages import age_on, today
from app.core.errors import AppError, database_errors_retryable
from app.notifications import service as notifications
from app.profiles.models import Profile
from app.support import service as support
from app.support.models import SupportRequest
from app.teens import access as teen_access
from app.teens import service as teens
from app.teens.models import TeenLink

# Super Admin and Admin 3.1 and 3.2's messages.
NO_RESULTS = "No clients match your search."
DEACTIVATE_CONFIRMATION = (
    "Deactivate {name}’s account? They won’t be able to sign in until it’s reactivated. "
    "Their information will be kept."
)
TEENS_AFFECTED = "This will also pause access for {count} teen account(s) linked to this account."
REACTIVATE_CONFIRMATION = "Reactivate {name}’s account? They’ll be able to sign in again."
DEACTIVATED = "{name}’s account has been deactivated."
REACTIVATED = "{name}’s account has been reactivated."
CONSENT_REVOKED = "Consent revoked"
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
CLIENT_NOT_FOUND = "We couldn’t find that client."
SUPER_ADMIN_ONLY = "Only the Super Admin can do this."


def _now() -> datetime:
    return datetime.now(UTC)


def _columns(now: datetime):
    """The listing's computed columns, over users outer-joined to subscriptions."""
    teen = is_teen()
    # 3.1 (6 Nov 19:22): "Scheduled for deletion" during the 10-day grace period, "Being
    # deleted" after it until the deletion is complete. The account's own request only.
    deletion_open = exists().where(
        DeletionRequest.account_id == User.id,
        DeletionRequest.profile_id.is_(None),
        DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
    )
    being_deleted = exists().where(
        DeletionRequest.account_id == User.id,
        DeletionRequest.profile_id.is_(None),
        DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        or_(
            DeletionRequest.locked_at.is_not(None),
            DeletionRequest.grace_ends_at.is_(None),
            DeletionRequest.grace_ends_at <= now,
        ),
    )
    revoked = exists().where(
        ConsentRevocation.account_id == User.id, ConsentRevocation.restored_at.is_(None)
    )
    status = case(
        (User.status == "deactivated", literal("deactivated")),
        (being_deleted, literal("being_deleted")),
        (deletion_open, literal("scheduled_for_deletion")),
        (revoked, literal("consent_revoked")),
        # A teen with their own account has no plan and can't revoke consent: of 3.1's
        # statuses, only Deactivated, Scheduled for deletion or Being deleted (their own) or
        # Active. Whether their
        # access is paused is in Client Details (teen_account.access).
        (teen, literal("active")),
        (Subscription.id.is_(None), literal("trial")),
        (Subscription.status == "past_due", literal("payment_issue")),
        (Subscription.status.in_(("cancelled", "ended")), literal("cancelled")),
        else_=literal("active"),
    )
    plan = case(
        (teen, null()),
        (subscription_gives_access(now), Subscription.plan),
        else_=literal("trial"),
    )
    members = (
        select(func.count(Profile.id))
        .where(
            Profile.account_id == User.id,
            Profile.is_self.is_(False),
            Profile.intake_completed_at.is_not(None),
        )
        .correlate(User)
        .scalar_subquery()
    )
    family = case((teen, null()), else_=members)
    last_active = (
        select(func.max(UserSession.last_seen_at))
        .where(UserSession.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    return teen, status, plan, family, last_active


def _is_super_admin(admin: User) -> bool:
    return admin.role == "super_admin"


def list_clients(
    db: Session,
    admin: User,
    *,
    search: str | None = None,
    account_type: AccountType | None = None,
    plan: ClientPlan | None = None,
    status: ClientStatus | None = None,
    state: str | None = None,
    signed_up_from=None,
    signed_up_to=None,
    limit: int = 50,
    offset: int = 0,
) -> ClientPage:
    """3.1's listing, newest accounts first. Search matches the first name or email; filters
    are account type, plan (Super Admin only), status, state and sign-up date."""
    if plan is not None and not _is_super_admin(admin):
        raise AppError(403, "super_admin_only", SUPER_ADMIN_ONLY, "plan")
    now = _now()
    teen, status_col, plan_col, family_col, last_active_col = _columns(now)
    query = (
        select(
            User.id,
            User.first_name,
            User.email,
            User.state,
            teen.label("is_teen"),
            plan_col.label("plan"),
            status_col.label("status"),
            family_col.label("family_members"),
            User.created_at,
            last_active_col.label("last_active_at"),
        )
        .outerjoin(Subscription, Subscription.account_id == User.id)
        .where(User.role == "client")
    )
    if search and search.strip():
        pattern = like(search.strip())
        query = query.where(
            or_(User.first_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    if account_type is not None:
        query = query.where(teen if account_type == "teen" else ~teen)
    if plan is not None:
        query = query.where(plan_col == plan)
    if status is not None:
        query = query.where(status_col == status)
    if state:
        query = query.where(User.state == state.strip().upper())
    start, end = day_range(signed_up_from, signed_up_to)
    if start is not None:
        query = query.where(User.created_at >= start)
    if end is not None:
        query = query.where(User.created_at < end)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
    ).all()
    super_admin = _is_super_admin(admin)
    items = [
        ClientRow(
            id=row.id,
            first_name=row.first_name,
            email=row.email,
            state=row.state,
            account_type="teen" if row.is_teen else "adult",
            plan=row.plan if super_admin else None,
            status=row.status,
            family_members=row.family_members,
            signed_up_at=row.created_at,
            last_active_at=row.last_active_at,
        )
        for row in rows
    ]
    return ClientPage(items=items, total=total, message=None if items else NO_RESULTS)


def load_client(db: Session, account_id: uuid.UUID, *, lock: bool = False) -> User:
    account = db.get(User, account_id, with_for_update=lock)
    if account is None or account.role != "client":
        raise AppError(404, "client_not_found", CLIENT_NOT_FOUND)
    return account


def _status(db: Session, account: User) -> ClientStatus:
    if account.status == "deactivated":
        return "deactivated"
    deletion = accounts.open_account_deletion(db, account)
    if deletion is not None:
        return "being_deleted" if accounts.grace_over(deletion) else "scheduled_for_deletion"
    if accounts.consent_revoked(db, account):
        return "consent_revoked"
    if support.is_teen_account(account):
        return "active"
    sub = entitlements.subscription(account)
    if sub is None:
        return "trial"
    if sub.status == "past_due":
        return "payment_issue"
    if sub.status in ("cancelled", "ended"):
        return "cancelled"
    return "active"


def _subscription(account: User) -> SubscriptionOut:
    sub = entitlements.subscription(account)
    if sub is None:
        return SubscriptionOut(plan="trial", status="trial", trial_ends_at=account.trial_ends_at)
    renews = sub.status == "active" and not sub.cancel_at_period_end
    return SubscriptionOut(
        plan=entitlements.plan(account),
        status={"past_due": "payment_issue"}.get(sub.status, sub.status),
        next_billing_date=sub.current_period_end if renews else None,
        add_on_members=sub.add_on_members,
    )


def _consent(db: Session, account: User) -> ConsentOut:
    accepted = [
        AcceptedPolicyOut(
            kind=policy.kind, title=policy.title, version=policy.version, accepted_at=at
        )
        for policy, at in db.execute(
            select(PolicyVersion, PolicyAcceptance.accepted_at)
            .join(PolicyAcceptance, PolicyAcceptance.policy_version_id == PolicyVersion.id)
            .where(PolicyAcceptance.user_id == account.id)
            .order_by(PolicyVersion.kind, PolicyVersion.published_at.desc())
        ).all()
    ]
    # The Health Consent the client accepted for their own profile (each version's first time).
    accepted += [
        AcceptedPolicyOut(
            kind=policy.kind, title=policy.title, version=policy.version, accepted_at=at
        )
        for policy, at in db.execute(
            select(PolicyVersion, func.min(HealthConsent.accepted_at))
            .join(HealthConsent, HealthConsent.policy_version_id == PolicyVersion.id)
            .join(Profile, Profile.id == HealthConsent.profile_id)
            .where(
                HealthConsent.accepted_by_id == account.id,
                Profile.account_id == account.id,
                Profile.is_self,
            )
            .group_by(PolicyVersion.id)
            .order_by(PolicyVersion.published_at.desc())
        ).all()
    ]
    revoked = accounts.consent_revoked(db, account)
    return ConsentOut(
        revoked=revoked, label=CONSENT_REVOKED if revoked else None, accepted=accepted
    )


def _family(db: Session, account: User) -> list[FamilyMemberOut]:
    members = db.scalars(
        select(Profile)
        .where(
            Profile.account_id == account.id,
            Profile.is_self.is_(False),
            Profile.intake_completed_at.is_not(None),
        )
        .order_by(Profile.created_at)
    )
    return [
        FamilyMemberOut(
            id=member.id,
            first_name=member.first_name,
            relationship=member.family_relationship,
            age=age_on(member.date_of_birth, today()) if member.date_of_birth else None,
            turned_off=member.turned_off_at is not None,
            deletion_requested=member.deletion_requested_at is not None,
        )
        for member in members
    ]


def _activity(db: Session, account: User) -> ActivityOut:
    last_active = db.scalar(
        select(func.max(UserSession.last_seen_at)).where(UserSession.user_id == account.id)
    )
    conversations = db.scalar(
        select(func.count())
        .select_from(Conversation)
        .join(Profile, Profile.id == Conversation.profile_id)
        .where(Profile.account_id == account.id, Conversation.deleted_at.is_(None))
    )
    requests = db.execute(
        select(SupportRequest.id, SupportRequest.kind)
        .where(SupportRequest.account_id == account.id, SupportRequest.status == "open")
        .order_by(SupportRequest.created_at)
    ).all()
    deletions = db.execute(
        select(DeletionRequest.id, DeletionRequest.kind, DeletionRequest.status)
        .where(
            DeletionRequest.account_id == account.id,
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        )
        .order_by(DeletionRequest.due_at)
    ).all()
    escalations = db.execute(
        select(Escalation.id, Escalation.level)
        .where(Escalation.account_id == account.id, Escalation.status == "not_reviewed")
        .order_by(Escalation.detected_at.desc())
    ).all()
    return ActivityOut(
        last_active_at=last_active,
        conversations=conversations or 0,
        open_support_requests=[OpenSupportRequest(id=i, kind=k) for i, k in requests],
        open_deletion_requests=[
            OpenDeletionRequest(id=i, kind=k, status=s) for i, k, s in deletions
        ],
        escalations_not_reviewed=[OpenEscalation(id=i, level=lv) for i, lv in escalations],
    )


def _linked_teens(db: Session, parent: User) -> list[TeenLink]:
    """The parent's teens who joined and aren't turned off: the teen accounts a deactivation
    pauses (3.2). Turned-off teens are paused already."""
    return list(
        db.scalars(
            select(TeenLink)
            .where(
                TeenLink.parent_account_id == parent.id,
                TeenLink.teen_account_id.is_not(None),
                TeenLink.turned_off_at.is_(None),
            )
            .order_by(TeenLink.created_at)
        )
    )


def _teen_count(db: Session, account: User) -> int:
    return len(_linked_teens(db, account))


def _audit_teen(db: Session, link: TeenLink, action: str, reason: str) -> None:
    audit.record(db, action, target_type="teen_link", target_id=link.id, details={"reason": reason})


def _pause_teens(db: Session, parent: User) -> int:
    """3.2: deactivating a parent pauses their invited teens. The access gate already shuts for a
    parent who isn't active (teens.access.parent_pause_reason), so this only tells each teen,
    with 12.1's access_paused notice ("Your access is paused. Please ask your parent or
    guardian..."), and audits it. Returns how many. The caller commits."""
    links = _linked_teens(db, parent)
    for link in links:
        teen = db.get(User, link.teen_account_id)
        if teen is not None and teen_access.is_teen_account(teen):
            notifications.notify(db, teen, "access_paused")
        _audit_teen(db, link, "teen.access_paused", "parent_deactivated")
    return len(links)


def _restored_teens(db: Session, parent: User) -> int:
    """3.2: reactivating a parent gives their invited teens their access back, if the Family plan
    and consent are still active; the gate works that out by itself. Audits the teens whose
    access is open again. No story text tells the teen, so nobody is notified. The caller
    commits."""
    restored = 0
    for link in _linked_teens(db, parent):
        if teen_access.parent_pause_reason(db, link, parent) is None:
            _audit_teen(db, link, "teen.access_restored", "parent_reactivated")
            restored += 1
    return restored


def _invited_teens(db: Session, parent: User) -> list[InvitedTeenOut]:
    """The parent's invited teens, with 8.2's status (Invite sent, Joined, Turned off or Access
    paused), and the first name the parent typed."""
    return [InvitedTeenOut(**row) for row in teens.admin_invited_teens(db, parent)]


def _teen_link(db: Session, teen: User) -> TeenLinkOut | None:
    """A teen's parent account, and whether the teen's access is active or paused."""
    link = teens.admin_teen_link(db, teen)
    return TeenLinkOut(**link) if link is not None else None


def client_detail(
    db: Session, admin: User, account_id: uuid.UUID, request: Request | None = None
) -> ClientDetail:
    """3.1's Client Details, with the client's health profile read-only (6 Nov 19:22). Every
    view is audited, with who did it and when, and whether a health profile was shown."""
    account = load_client(db, account_id)
    status = _status(db, account)
    teen = support.is_teen_account(account)
    teen_count = 0 if teen else _teen_count(db, account)
    email_change = support.open_email_change(db, account)
    detail = ClientDetail(
        id=account.id,
        account=AccountOut(
            first_name=account.first_name,
            email=account.email,
            state=account.state,
            state_name=STATE_NAMES.get(account.state) if account.state else None,
            zip_code=account.zip_code,
            account_type="teen" if teen else "adult",
            signed_up_at=account.created_at,
            status=status,
        ),
        subscription=_subscription(account) if _is_super_admin(admin) and not teen else None,
        consent=_consent(db, account),
        family_members=[] if teen else _family(db, account),
        invited_teens=[] if teen else _invited_teens(db, account),
        teen_account=_teen_link(db, account) if teen else None,
        activity=_activity(db, account),
        health_profile=health_profile(db, account),
        email_change_request_id=email_change.id if email_change else None,
        can_deactivate=account.status != "deactivated",
        can_reactivate=account.status == "deactivated",
        confirmations=ConfirmationsOut(
            deactivate=DEACTIVATE_CONFIRMATION.format(name=account.first_name),
            teens_affected=TEENS_AFFECTED.format(count=teen_count) if teen_count else None,
            reactivate=REACTIVATE_CONFIRMATION.format(name=account.first_name),
        ),
    )
    with database_errors_retryable(db):
        audit.record(
            db,
            "admin.client_viewed",
            actor_id=admin.id,
            target_type="user",
            target_id=account.id,
            request=request,
            details={"health_profile_shown": detail.health_profile is not None},
        )
        db.commit()
    return detail


def deactivate(
    db: Session, admin: User, account_id: uuid.UUID, reason: str, request: Request | None = None
) -> ClientActionOut:
    """3.2's Deactivate, with the mandatory reason (recorded in the audit event). Signs the
    client out on every device straight away. Deactivating a deactivated account changes
    nothing."""
    with database_errors_retryable(db):
        account = load_client(db, account_id, lock=True)
        if account.status != "deactivated":
            account.status = "deactivated"
            db.execute(
                update(UserSession)
                .where(UserSession.user_id == account.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=_now(), revoked_reason="account_deactivated")
                .execution_options(synchronize_session=False)
            )
            # A deactivated teen's parent isn't affected or told; a parent's teens are paused.
            teen_count = 0 if support.is_teen_account(account) else _pause_teens(db, account)
            audit.record(
                db,
                "admin.client_deactivated",
                actor_id=admin.id,
                target_type="user",
                target_id=account.id,
                request=request,
                details={"reason": reason, "teen_accounts_paused": teen_count},
            )
        name = account.first_name
        db.commit()
    return ClientActionOut(status="deactivated", message=DEACTIVATED.format(name=name))


def reactivate(
    db: Session, admin: User, account_id: uuid.UUID, request: Request | None = None
) -> ClientActionOut:
    """3.2's Reactivate: the client can sign in again with everything intact, and their
    notifications restart. Reactivating an active account changes nothing."""
    with database_errors_retryable(db):
        account = load_client(db, account_id, lock=True)
        if account.status == "deactivated":
            account.status = "active"
            db.flush()  # the access gate reads the parent's status
            restored = 0 if support.is_teen_account(account) else _restored_teens(db, account)
            audit.record(
                db,
                "admin.client_reactivated",
                actor_id=admin.id,
                target_type="user",
                target_id=account.id,
                request=request,
                details={"teen_accounts_restored": restored},
            )
        name = account.first_name
        db.commit()
        status = _status(db, account)
    return ClientActionOut(status=status, message=REACTIVATED.format(name=name))
