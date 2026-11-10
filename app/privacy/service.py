"""Privacy & Data (story 11.4): the screen, revoking consent and deletion requests; the timeline
every deletion request follows (8.2, 11.4, Super Admin 5.2); and the support team's side of
deletion requests. Decisions: docs/decisions/deletion-flow-1922.md.

The timeline, for every kind (an Account Deletion, a Family Member Deletion, an Invited Teen
Removal, a Teen Deletion):

1. The request is acknowledged straight away (a notice with its email copy, or an email).
2. A 10-day grace period (`grace_period`): everything stays fully usable, the deletion date is
   shown, and the team can't complete it yet.
3. The privacy sweep ends it (`end_grace_periods`): the account or family member's profile is
   locked, the request goes to Pending review, and the team is told.
4. The team completes it within 45 calendar days of the request; the purge job deletes the data
   (app/privacy/purge.py) and the client, and any teen affected, is emailed.

What still works (the endpoints take PrivacySession, which skips the policy gate but refuses an
account locked for deletion):

| State                          | Privacy & Data | Export | Revoke consent | Delete      |
| ------------------------------ | -------------- | ------ | -------------- | ----------- |
| Consent revoked                | yes            | yes    | already done   | yes         |
| Updated policies not accepted  | yes            | yes    | yes            | yes         |
| In a deletion's grace period   | yes            | yes    | no (409)       | no (409)    |
| Locked after the grace period  | no (403)       | no     | no             | no          |
| Invited teen who lost access   | yes            | yes    | never (teens)  | yes (teen)  |

Lock order: the account row, then the deletion request, then profiles. A cascading DELETE FROM
users takes the account first too.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.accounts.models import (
    ACCOUNT_DELETION_KINDS,
    OPEN_DELETION_STATUSES,
    ConsentRevocation,
    DeletionRequest,
    PolicyAcceptance,
    PolicyVersion,
)
from app.auth.models import User
from app.conversations.models import HealthConsent
from app.core import audit, jobs
from app.core.config import settings
from app.core.email import EmailMessage, SendEmail
from app.core.errors import AppError, database_errors_retryable
from app.core.jobs import Job
from app.notifications import service as notifications
from app.privacy import emails, export, teens
from app.privacy.schemas import (
    AcceptedPolicyOut,
    DeletionNoticeOut,
    DeletionRequested,
    DeletionRequestOut,
    FamilyMemberName,
    PrivacyOut,
)
from app.profiles.models import Profile
from app.support import service as support

# Job kinds, run by app/privacy/jobs.py. Payloads hold the deletion request's id only.
NOTIFY_TEAM_JOB = "privacy.notify_team"  # emails the team about a request ready for review
PURGE_JOB = "privacy.purge_request"  # deletes the data of a completed request
COMPLETION_EMAIL_JOB = "privacy.completion_email"  # "your deletion is complete"
SWEEP_JOB = "privacy.sweep"  # grace periods, team emails, deleted conversations
# Key for pg_advisory_xact_lock, so two workers starting at once don't both start a sweep.
SWEEP_LOCK_KEY = 9_120_402

# Story 11.4's messages.
CANT_PROCESS = "We can’t process your request at the moment. Please try again later."
EXPORT_FIRST = "Would you like to export your data before deleting your account?"
DELETE_CONFIRMATION = (
    "Delete your account? You’ll have 10 days to keep using Your Oracle and download your "
    "information. After that, it will be permanently deleted."
)
DELETE_DISCLAIMER = (
    "Deleting your account will permanently delete your information, and the information of "
    "everyone on your account, including your family members and any teens on your plan. "
    "You’ll all have 10 days to keep using Your Oracle and download your information before "
    "the deletion begins. This can’t be undone."
)
TEEN_DELETE_CONFIRMATION = (
    "Delete all your information? You’ll have 10 days to keep using Your Oracle and download "
    "your information. After that, your account will be closed."
)
# Story 11.4's "Export failed".
EXPORT_FAILED = "We couldn’t download your data just now. Please try again."
# Super Admin 5.2's messages.
CHECKLIST_INCOMPLETE = "Please complete the review checklist first."
ON_LEGAL_HOLD = "This request is on legal hold. The Client has been told."

# Not in the stories (docs/decisions/phase-10-account.md, deletion-flow-1922.md).
CONSENT_REVOKED = (
    "Your consent has been revoked, and you’ve been signed out on all your devices. Your "
    "information has been kept."
)
TEEN_CANNOT_REVOKE = (
    "Your parent or guardian gave consent for your account, so it can’t be revoked here."
)
REQUEST_NOT_FOUND = "We couldn’t find that deletion request."
NOT_ALLOWED = "Only the support team can do that."
ALREADY_COMPLETED = "This request has already been completed."
ALREADY_DECLINED = "This request has been declined."
IN_PROGRESS = "This request is in progress."
HOLD_LIFTED = "The legal hold has been lifted."
DECLINED = "This deletion request has been declined."


def _now() -> datetime:
    return datetime.now(UTC)


def grace_message(deletion: DeletionRequest) -> str:
    """Super Admin 5.2's "Grace period not ended"."""
    end = deletion.grace_ends_at or _now()
    return (
        f"This request can be completed after the grace period ends on {accounts.long_date(end)}."
    )


# What the screen shows


def _family_members(db: Session, account: User) -> list[Profile]:
    """Finished family members, turned off or not, oldest first: everyone on the account."""
    return list(
        db.scalars(
            select(Profile)
            .where(
                Profile.account_id == account.id,
                Profile.is_self.is_(False),
                Profile.intake_completed_at.is_not(None),
            )
            .order_by(Profile.created_at)
        )
    )


def _accepted_policies(db: Session, account: User) -> list[AcceptedPolicyOut]:
    """Each policy's latest version the client accepted, with the date: the Terms of Service
    and Privacy Policy from the account, the Health Consent from any profile it was accepted
    for (the client's own, or as a family member's advocate)."""
    rows = db.execute(
        select(PolicyVersion, PolicyAcceptance.accepted_at)
        .join(PolicyAcceptance, PolicyAcceptance.policy_version_id == PolicyVersion.id)
        .where(PolicyAcceptance.user_id == account.id)
        .order_by(PolicyVersion.kind, PolicyVersion.published_at.desc())
        .ext(distinct_on(PolicyVersion.kind))
    ).all()
    consent = db.execute(
        select(PolicyVersion, HealthConsent.accepted_at)
        .join(HealthConsent, HealthConsent.policy_version_id == PolicyVersion.id)
        .where(HealthConsent.accepted_by_id == account.id)
        .order_by(PolicyVersion.published_at.desc(), HealthConsent.accepted_at.desc())
        .limit(1)
    ).first()
    if consent is not None:
        rows.append(consent)
    order = {"terms": 0, "privacy": 1, "health_consent": 2}
    return [
        AcceptedPolicyOut(
            kind=policy.kind,
            title=policy.title,
            version=policy.version,
            url=policy.url,
            accepted_at=accepted_at,
        )
        for policy, accepted_at in sorted(rows, key=lambda row: order.get(row[0].kind, 9))
        if policy.kind in order
    ]


def request_out(deletion: DeletionRequest) -> DeletionRequestOut:
    return DeletionRequestOut(
        id=deletion.id,
        kind=deletion.kind,
        status=deletion.status,
        requested_at=deletion.requested_at,
        grace_ends_at=deletion.grace_ends_at,
        due_at=deletion.due_at,
    )


def notice_out(db: Session, account: User) -> DeletionNoticeOut | None:
    """The grace period's date, banner and (for an invited teen) message (1.2, 8.2, 11.4)."""
    notice = accounts.deletion_notice(db, account)
    if notice is None:
        return None
    deletion_on, banner, message = notice
    return DeletionNoticeOut(deletion_on=deletion_on, banner=banner, message=message)


def privacy_screen(db: Session, account: User) -> PrivacyOut:
    """Story 11.4's Privacy & Data screen. A teen with their own account sees Export My Data
    and Delete My Information only (`account_type` "teen", `can_revoke_consent` false)."""
    teen = support.is_teen_account(account)
    deletion = accounts.open_account_deletion(db, account)
    revoked = accounts.consent_revoked(db, account)
    members = [] if teen else _family_members(db, account)
    invited = [] if teen else teens.invited_teen_names(db, account)
    return PrivacyOut(
        account_type="teen" if teen else "adult",
        accepted_policies=_accepted_policies(db, account),
        consent_revoked=revoked,
        can_revoke_consent=not teen and not revoked and deletion is None,
        deletion_request=request_out(deletion) if deletion else None,
        deletion_notice=notice_out(db, account),
        family_members=[
            FamilyMemberName(profile_id=member.id, first_name=member.first_name)
            for member in members
        ],
        invited_teens=invited,
        export_first=EXPORT_FIRST,
        delete_confirmation=TEEN_DELETE_CONFIRMATION if teen else DELETE_CONFIRMATION,
        delete_disclaimer=DELETE_DISCLAIMER if members or invited else None,
    )


# Export My Data


def export_my_data(db: Session, account: User, request: Request) -> tuple[bytes, str]:
    """Story 11.4: the file is made and sent straight back, in the app; nothing is kept or
    emailed, and no team is involved. Works during a deletion's grace period ("they can
    download their data at any time"). Audited with no details. A database failure gets the
    story's "Export failed" message, and the client can try again."""
    try:
        body, filename = export.export_file(db, account)
        audit.record(
            db,
            "account.data_exported",
            actor_id=account.id,
            target_type="user",
            target_id=account.id,
            request=request,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "export_failed", EXPORT_FAILED) from None
    return body, filename


# Revoke Consent


def revoke_consent(db: Session, account: User, request: Request) -> str:
    """Story 11.4: the client's consent is withdrawn for the whole account, family members'
    profiles included. They're signed out on all devices straight away; the Oracle, analytics
    and notifications stop using their information (the policy gate and
    notifications.consent_revoked); invited teens are paused; nothing is deleted. Signing in
    again shows the Terms of Service, Privacy Policy and Health Consent
    (accounts.service.pending_policies), and accepting them gives consent again.

    Not while the account has an open deletion request (as built in Phase 10; see the open
    questions). Scheduled reminders aren't cancelled: any that fall due while consent is revoked
    are dropped when they're due, and later ones go again once it's given back. Safe to
    repeat."""
    if support.is_teen_account(account):
        raise AppError(403, "teen_cannot_revoke", TEEN_CANNOT_REVOKE)
    try:
        db.refresh(account, with_for_update=True)
        if accounts.open_account_deletion(db, account) is not None:
            db.rollback()
            raise AppError(409, "deletion_requested", accounts.ALREADY_SCHEDULED)
        if accounts.consent_revoked(db, account):
            db.rollback()
            return CONSENT_REVOKED
        db.add(ConsentRevocation(account_id=account.id, revoked_at=_now()))
        ended = accounts.sign_out_everywhere(db, account, forget_devices=False)
        teens.pause_for_revoked_consent(db, account)
        audit.record(
            db,
            "consent.revoked",
            actor_id=account.id,
            target_type="user",
            target_id=account.id,
            request=request,
            details={"sessions_ended": ended},
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "request_failed", CANT_PROCESS) from None
    return CONSENT_REVOKED


# New requests: the grace period and the acknowledgement


def _audit_request(
    db: Session,
    deletion: DeletionRequest,
    actor_id: uuid.UUID | None,
    request: Request | None,
    action: str,
    **details: object,
) -> None:
    """Ids and the request's type only: never names, emails or health data."""
    audit.record(
        db,
        action,
        actor_id=actor_id,
        target_type="deletion_request",
        target_id=deletion.id,
        request=request,
        details={"kind": deletion.kind, **details},
    )


def start_request(
    db: Session,
    *,
    account_id: uuid.UUID,
    kind: str,
    actor_id: uuid.UUID,
    request: Request | None,
    profile_id: uuid.UUID | None = None,
    requested_by_id: uuid.UUID | None = None,
) -> DeletionRequest:
    """Adds a request in its 10-day grace period, due 45 calendar days from now, audited as the
    request and the start of its grace period. Nothing is locked yet, and the team isn't told
    until the grace period ends (Super Admin 11.1). The caller holds the locks, acknowledges it
    and commits."""
    now = _now()
    deletion = DeletionRequest(
        account_id=account_id,
        profile_id=profile_id,
        kind=kind,
        requested_by_id=requested_by_id,
        source="in_app",
        status="grace_period",
        requested_at=now,
        grace_ends_at=now + timedelta(days=settings.deletion_grace_days),
        due_at=now + timedelta(days=settings.deletion_due_days),
    )
    db.add(deletion)
    db.flush()
    _audit_request(db, deletion, actor_id, request, "deletion.requested")
    _audit_request(
        db,
        deletion,
        actor_id,
        request,
        "deletion.grace_period_started",
        grace_ends_at=deletion.grace_ends_at.isoformat(),
    )
    return deletion


def _acknowledge(
    db: Session, account: User, deletion: DeletionRequest, request: Request | None
) -> EmailMessage | None:
    """Story 11.4 and Super Admin 5.2: the acknowledgement, straight away, with the date the
    grace period ends. It's the notice for the account (with its email copy): 11.4's email text
    for an adult's Account Deletion, 12.1's teen deletion notice for a teen. When the notice
    can't go (consent revoked, or deactivated), the same text is returned to be emailed
    directly once the caller has committed."""
    date = accounts.long_date(deletion.grace_ends_at)
    teen = support.is_teen_account(account)
    kind = "teen_deletion_notice" if teen else "deletion_acknowledged"
    sent = notifications.notify(db, account, kind, data={"date": date})
    _audit_request(db, deletion, account.id, request, "deletion.acknowledged")
    if sent is not None:
        return None
    return (
        emails.teen_deletion_notice(account.email, date)
        if teen
        else emails.acknowledgement(account.email, date)
    )


def _tell_invited_teens(db: Session, parent: User, deletion: DeletionRequest) -> None:
    """Story 11.4: the parent's invited teens are notified at the start (12.1's deletion notice),
    and keep full use of their own accounts for the grace period. Turned-off teens are told too:
    their accounts are deleted with the parent's. The caller commits."""
    date = accounts.long_date(deletion.grace_ends_at)
    for teen_id in teens.invited_teen_accounts(db, parent.id):
        teen = db.get(User, teen_id)
        if teen is not None:
            notifications.notify(db, teen, "teen_deletion_notice", data={"date": date})


def _requested(deletion: DeletionRequest) -> DeletionRequested:
    return DeletionRequested(
        message=accounts.scheduled_banner(deletion.grace_ends_at),
        deletion_request=request_out(deletion),
    )


def request_deletion(
    db: Session, account: User, send: SendEmail, request: Request
) -> DeletionRequested:
    """Story 11.4's Delete Account (Delete My Information for a teen with their own account):
    an Account Deletion of the client's account, every managed family member's data, and their
    invited teens' accounts and data. The app has asked "Would you like to export your data
    first?" and shown the disclaimer naming everyone affected (GET /me/privacy).

    The client is acknowledged straight away, keeps full use for the 10-day grace period with
    the banner, and their invited teens are told. Then the sweep locks the account and the
    teens', and the team reviews it. "Stay as advocate only" is deferred to a later release, and
    transferring profiles was removed (6 Nov 19:22)."""
    if support.is_teen_account(account):
        return request_teen_deletion(db, account, send, request)
    try:
        db.refresh(account, with_for_update=True)
        if accounts.open_account_deletion(db, account) is not None:
            db.rollback()
            raise AppError(409, "already_scheduled", accounts.ALREADY_SCHEDULED)
        deletion = start_request(
            db, account_id=account.id, kind="account", actor_id=account.id, request=request
        )
        fallback = _acknowledge(db, account, deletion, request)
        _tell_invited_teens(db, account, deletion)
        result = _requested(deletion)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "request_failed", CANT_PROCESS) from None
    if fallback is not None:
        send(fallback)
    return result


def request_teen_deletion(
    db: Session, teen: User, send: SendEmail, request: Request | None
) -> DeletionRequested:
    """Story 11.4's Delete My Information, for a teen with their own account, including one who
    has lost access. A Teen Deletion from the app (Super Admin 5.2), with the identity
    confirmed by the teen's own sign-in. The parent can't see it. The teen is acknowledged,
    keeps full use for the grace period with the banner, and is then locked; once the team
    completes it, the purge deletes the account and data and removes them from the parent's
    family (the place is freed)."""
    try:
        db.refresh(teen, with_for_update=True)
        if accounts.open_account_deletion(db, teen) is not None:
            db.rollback()
            raise AppError(409, "already_scheduled", accounts.ALREADY_SCHEDULED)
        deletion = start_request(
            db, account_id=teen.id, kind="teen", actor_id=teen.id, request=request
        )
        fallback = _acknowledge(db, teen, deletion, request)
        result = _requested(deletion)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "request_failed", CANT_PROCESS) from None
    if fallback is not None:
        send(fallback)
    return result


def request_teen_removal(
    db: Session, parent: User, teen_id: uuid.UUID, request: Request | None
) -> DeletionRequest | None:
    """Story 8.2's Remove for an invited teen who joined (teens.service.remove, which has
    already deleted the link, so the place is free): an Invited Teen Removal of the teen's
    account and data. The teen is told (12.1's deletion notice), keeps full use of their account
    for the grace period (teens.access.in_removal_grace), and is then locked.

    A teen whose account already has an open deletion request (their own) isn't given a second
    one. The caller holds the link and parent locks, and commits."""
    teen = db.get(User, teen_id, with_for_update=True)
    if teen is None or not support.is_teen_account(teen):
        return None
    if accounts.open_account_deletion(db, teen) is not None:
        return None
    deletion = start_request(
        db,
        account_id=teen.id,
        kind="teen_removal",
        actor_id=parent.id,
        request=request,
        requested_by_id=parent.id,
    )
    date = accounts.long_date(deletion.grace_ends_at)
    notifications.notify(db, teen, "teen_deletion_notice", data={"date": date})
    _audit_request(db, deletion, parent.id, request, "deletion.acknowledged")
    return deletion


# The end of the grace period, and its reminder (run by the privacy sweep)


def _lock(db: Session, deletion: DeletionRequest, now: datetime) -> None:
    """Story 8.2 and 11.4's "after the grace period": the account (and, for an Account Deletion,
    its invited teens' accounts) or the family member's profile is locked, and their scheduled
    reminders are cancelled. The account lock itself is accounts.service.deletion_locked, which
    reads `locked_at`; a family member's profile gets `deletion_requested_at`, which every
    package already refuses (OwnedProfile's users, conversations, notifications)."""
    deletion.locked_at = now
    account = db.get(User, deletion.account_id)
    if deletion.kind == "family_member":
        profile = db.get(Profile, deletion.profile_id, with_for_update=True)
        if profile is not None and profile.account_id == deletion.account_id:
            profile.deletion_requested_at = now
            if account is not None:
                notifications.cancel_scheduled(db, account, profile=profile)
        return
    if account is None:
        return
    notifications.cancel_scheduled(db, account)
    if deletion.kind == "account":
        for teen_id in teens.invited_teen_accounts(db, account.id):
            teen = db.get(User, teen_id)
            if teen is not None:
                notifications.cancel_scheduled(db, teen)


def end_grace_periods(db: Session, now: datetime) -> int:
    """Super Admin 5.2: "The grace period ends automatically after 10 days, and the status
    changes without anyone acting." Each request whose grace period has ended is locked, goes
    to Pending review (one on legal hold stays on hold), and the team is told: the team email
    job and the admin notice (11.1). One commit per request. Returns how many."""
    from app.admin.notifications import notify_admins  # here: admin imports this package

    ids = db.scalars(
        select(DeletionRequest.id)
        .where(
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
            DeletionRequest.locked_at.is_(None),
            DeletionRequest.grace_ends_at <= now,
        )
        .order_by(DeletionRequest.grace_ends_at)
        .limit(settings.privacy_sweep_batch_size)
    ).all()
    done = 0
    for deletion_id in ids:
        deletion = db.get(
            DeletionRequest, deletion_id, with_for_update=True, populate_existing=True
        )
        if deletion is None or deletion.locked_at is not None:
            db.rollback()
            continue
        if deletion.status not in OPEN_DELETION_STATUSES:
            db.rollback()
            continue
        _lock(db, deletion, now)
        if deletion.status == "grace_period":
            deletion.status = "pending"
        jobs.enqueue(db, NOTIFY_TEAM_JOB, {"deletion_request_id": str(deletion.id)})
        notify_admins(db, "deletion_request", target_id=deletion.id)
        _audit_request(db, deletion, None, None, "deletion.grace_period_ended")
        db.commit()
        done += 1
    return done


def send_grace_reminders(db: Session, now: datetime) -> int:
    """Story 12.1's grace period reminder, once, the day before an account's deletion: "Your
    account will be deleted tomorrow. Download your information now if you’d like a copy." For
    an Account Deletion, the invited teens get it too. Family members' deletions have none (the
    story gives none). One commit per request. Returns how many requests were reminded."""
    soon = now + timedelta(hours=settings.deletion_grace_reminder_hours)
    ids = db.scalars(
        select(DeletionRequest.id)
        .where(
            DeletionRequest.kind.in_(ACCOUNT_DELETION_KINDS),
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
            DeletionRequest.locked_at.is_(None),
            DeletionRequest.grace_reminded_at.is_(None),
            DeletionRequest.grace_ends_at > now,
            DeletionRequest.grace_ends_at <= soon,
        )
        .order_by(DeletionRequest.grace_ends_at)
        .limit(settings.privacy_sweep_batch_size)
    ).all()
    for deletion_id in ids:
        deletion = db.get(
            DeletionRequest, deletion_id, with_for_update=True, populate_existing=True
        )
        if deletion is None or deletion.grace_reminded_at is not None:
            db.rollback()
            continue
        deletion.grace_reminded_at = now
        account = db.get(User, deletion.account_id)
        if account is not None:
            teen = support.is_teen_account(account)
            notifications.notify(
                db, account, "teen_deletion_reminder" if teen else "deletion_reminder"
            )
            if deletion.kind == "account":
                for teen_id in teens.invited_teen_accounts(db, account.id):
                    invited = db.get(User, teen_id)
                    if invited is not None:
                        notifications.notify(db, invited, "teen_deletion_reminder")
        db.commit()
    return len(ids)


# The support team's side (Super Admin 5.2), for the admin endpoints. The callers check the
# admin's sign-in; these functions check the role again.


def _check_team_member(admin: User) -> None:
    if admin.role not in support.TEAM_ROLES:
        raise AppError(403, "not_allowed", NOT_ALLOWED)


def _load(db: Session, request_id: uuid.UUID) -> DeletionRequest:
    deletion = db.get(DeletionRequest, request_id, with_for_update=True)
    if deletion is None:
        raise AppError(404, "deletion_request_not_found", REQUEST_NOT_FOUND)
    return deletion


def _refuse_closed(deletion: DeletionRequest) -> None:
    if deletion.status == "completed":
        raise AppError(409, "already_completed", ALREADY_COMPLETED)
    if deletion.status == "declined":
        raise AppError(409, "declined", ALREADY_DECLINED)


def _refuse_grace(deletion: DeletionRequest) -> None:
    """Super Admin 5.2: a request in its grace period can be viewed, not completed."""
    if deletion.status == "grace_period":
        raise AppError(409, "grace_period", grace_message(deletion))


def start_review(
    db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None
) -> str:
    """Super Admin 5.2's "In progress": the team has started on a request pending review."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        deletion = _load(db, request_id)
        _refuse_closed(deletion)
        _refuse_grace(deletion)
        if deletion.status == "pending":
            deletion.status = "in_progress"
            _audit_request(db, deletion, admin.id, request, "deletion.review_started")
        db.commit()
    return IN_PROGRESS


def complete_request(
    db: Session,
    admin: User,
    request_id: uuid.UUID,
    *,
    identity_confirmed: bool,
    legal_hold_checked: bool,
    request: Request | None = None,
) -> str:
    """Super Admin 5.2's Complete deletion, once the grace period has ended (Pending review or
    In progress) and after the review checklist (identity confirmed, legal hold checked). The
    request is marked completed and the purge job deletes the data its type covers within a
    minute, then emails the client and any teen affected. The returned text is Super Admin
    5.2's "Deletion completed"."""
    _check_team_member(admin)
    if not (identity_confirmed and legal_hold_checked):
        raise AppError(422, "checklist_incomplete", CHECKLIST_INCOMPLETE)
    with database_errors_retryable(db):
        deletion = _load(db, request_id)
        _refuse_closed(deletion)
        _refuse_grace(deletion)
        if deletion.status == "on_legal_hold":
            raise AppError(409, "on_legal_hold", ON_LEGAL_HOLD)
        account = db.get(User, deletion.account_id)
        name = account.first_name if account is not None else ""
        deletion.status = "completed"
        deletion.completed_at = _now()
        deletion.completed_by_id = admin.id
        jobs.enqueue(db, PURGE_JOB, {"deletion_request_id": str(deletion.id)})
        _audit_request(db, deletion, admin.id, request, "deletion.completed")
        db.commit()
    return f"The deletion is complete, and {name} has been emailed."


def place_legal_hold(
    db: Session,
    admin: User,
    request_id: uuid.UUID,
    send: SendEmail,
    request: Request | None = None,
) -> str:
    """Super Admin 5.2's Place on legal hold: the deletion waits, and the client is told by
    email. Also possible during the grace period (which still ends on its date) and on a
    completed request the purge hasn't carried out yet, which then waits too. The team's note
    goes in the admin package's notes field."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        deletion = _load(db, request_id)
        if deletion.purged_at is not None or deletion.status == "declined":
            _refuse_closed(deletion)
        if deletion.status == "on_legal_hold":
            db.rollback()
            return ON_LEGAL_HOLD
        deletion.status = "on_legal_hold"
        deletion.completed_at = None
        deletion.completed_by_id = None
        deletion.legal_hold_at = _now()
        _audit_request(db, deletion, admin.id, request, "deletion.legal_hold_placed")
        account = db.get(User, deletion.account_id)
        email = account.email if account is not None else None
        db.commit()
    if email is not None:
        send(emails.legal_hold(email))
    return ON_LEGAL_HOLD


def lift_legal_hold(
    db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None
) -> str:
    """The hold is lifted: the request goes back to its grace period if that hasn't ended yet,
    or to Pending review, and the team completes it as usual."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        deletion = _load(db, request_id)
        if deletion.status == "on_legal_hold":
            deletion.status = "pending" if accounts.grace_over(deletion) else "grace_period"
            deletion.legal_hold_at = None
            _audit_request(db, deletion, admin.id, request, "deletion.legal_hold_lifted")
        db.commit()
    return HOLD_LIFTED


def decline_request(
    db: Session, admin: User, request_id: uuid.UUID, request: Request | None = None
) -> str:
    """Turns a request down (r2's "declined"): the profile or account is back in use as it
    was. Not in the stories; for the team's mistakes and requests that turn out not to be the
    client's. A declined Invited Teen Removal doesn't link the teen to the family again."""
    _check_team_member(admin)
    with database_errors_retryable(db):
        deletion = _load(db, request_id)
        _refuse_closed(deletion)
        deletion.status = "declined"
        deletion.legal_hold_at = None
        if deletion.profile_id is not None:
            profile = db.get(Profile, deletion.profile_id, with_for_update=True)
            if profile is not None and profile.account_id == deletion.account_id:
                profile.deletion_requested_at = None
        _audit_request(db, deletion, admin.id, request, "deletion.declined")
        db.commit()
    return DECLINED


# The team's email about each request ready for review


def notify_team(db: Session, deletion_request_id: uuid.UUID, send: SendEmail) -> None:
    """Emails the support team about one request (NOTIFY_TEAM_JOB). Once only, and never during
    the grace period. The worker commits."""
    deletion = db.get(DeletionRequest, deletion_request_id, with_for_update=True)
    if deletion is None or deletion.team_notified_at is not None:
        return
    if deletion.locked_at is None and deletion.status == "grace_period":
        return
    send(emails.new_deletion_request(settings.support_team_email, deletion))
    deletion.team_notified_at = _now()


def queue_team_emails(db: Session, now: datetime) -> int:
    """A safety net for requests past their grace period whose team email wasn't queued (a job
    lost, or rows from before this flow): queues it for any not yet notified and not already
    queued. Returns how many were queued."""
    queued = exists().where(
        Job.kind == NOTIFY_TEAM_JOB,
        Job.status.in_(("pending", "running")),
        Job.payload["deletion_request_id"].astext == cast(DeletionRequest.id, String),
    )
    ids = db.scalars(
        select(DeletionRequest.id)
        .where(
            DeletionRequest.team_notified_at.is_(None),
            DeletionRequest.locked_at.is_not(None),
            DeletionRequest.locked_at <= now - timedelta(minutes=1),
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
            ~queued,
        )
        .order_by(DeletionRequest.requested_at)
        .limit(settings.privacy_sweep_batch_size)
    ).all()
    for deletion_id in ids:
        jobs.enqueue(db, NOTIFY_TEAM_JOB, {"deletion_request_id": str(deletion_id)})
    return len(ids)


def ensure_sweep(db: Session, run_at: datetime | None = None) -> None:
    """Makes sure one privacy sweep is waiting to run. Caller commits."""
    db.execute(select(func.pg_advisory_xact_lock(SWEEP_LOCK_KEY)))
    waiting = db.scalar(
        select(Job.id).where(Job.kind == SWEEP_JOB, Job.status == "pending").limit(1)
    )
    if waiting is None:
        jobs.enqueue(db, SWEEP_JOB, run_at=run_at)
