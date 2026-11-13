"""The purge: deletes the data of deletion requests the support team has completed (Super Admin
5.2), and conversations clients deleted (docs/PLAN.md, question 45).

What each request deletes (6 Nov 19:22):

- family_member (8.2): the member's profile and everything keyed by it (conversations and
  their messages and feedback, Health Consents, the health profile, notifications); the client
  is told "[Name]’s data has been deleted." and the place is free;
- account (11.4): the client's account with every profile on it, and the accounts and data of
  the client's invited teens. The client is emailed, and each teen gets 11.4's "Your account
  has been deleted because your parent or guardian deleted their account...";
- teen_removal (8.2): the removed teen's account and data. The teen and the parent who removed
  them are emailed;
- teen (11.4): the teen's account and data, after removing them from the parent's family (the
  place is freed; the parent isn't told why). The teen is emailed.

Never deleted: the audit log, escalation records (story 3.2: kept 6 years; plain ids, no
foreign keys), and the deletion requests themselves (no names or health data).

Legal holds: a request on hold isn't purged (its status isn't "completed"), and a client's
deleted conversations wait while any of the account's requests is on hold.

Feedback comments are health data: they're deleted explicitly with their messages, not left to
the foreign keys' cascade.

Backups: rows deleted here leave the live database at once. Deletion "including from backups"
depends on the backup retention, which must fit within the 45 calendar days
(docs/decisions/deletion-flow-1922.md).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.accounts.models import OPEN_DELETION_STATUSES, DeletionRequest
from app.auth.models import User
from app.billing.dependencies import get_payment_provider
from app.billing.models import Subscription
from app.billing.provider import STORES
from app.conversations.models import Conversation, Message, MessageFeedback
from app.core import audit, jobs
from app.core.config import settings
from app.core.email import EmailMessage, SendEmail
from app.notifications import service as notifications
from app.privacy import emails, teens
from app.privacy.service import COMPLETION_EMAIL_JOB
from app.profiles.models import Profile


def _now() -> datetime:
    return datetime.now(UTC)


def _delete_conversations(db: Session, conversation_ids) -> None:
    """Deletes conversations with their messages, and the feedback on those messages first.
    `conversation_ids` may be a list or a subquery. Escalations aren't touched."""
    messages = select(Message.id).where(Message.conversation_id.in_(conversation_ids))
    db.execute(delete(MessageFeedback).where(MessageFeedback.message_id.in_(messages)))
    db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))


def purge_profile(db: Session, account: User | None, profile: Profile) -> None:
    """Deletes one profile and everything keyed by it. The database's ON DELETE CASCADE takes
    the rest: Health Consents, notifications, the health profile and its answers, billing's
    paused-member record; support requests keep their row with the profile set to null. The
    caller holds the profile's lock and commits."""
    if account is not None:
        notifications.cancel_scheduled(db, account, profile=profile)
    _delete_conversations(db, select(Conversation.id).where(Conversation.profile_id == profile.id))
    db.execute(delete(Profile).where(Profile.id == profile.id))


def _purge_family_member(db: Session, deletion: DeletionRequest) -> None:
    """8.2's removal. Locks the member, then the account, like 8.2's actions."""
    profile = db.get(Profile, deletion.profile_id, with_for_update=True)
    account = db.get(User, deletion.account_id, with_for_update=True)
    if profile is None or profile.account_id != deletion.account_id:
        return  # already gone with its account
    name = profile.first_name
    purge_profile(db, account, profile)
    if account is not None:
        # 8.2: "[Name]’s data has been deleted." The member is gone, so the name is passed in.
        notifications.notify(db, account, "deletion_complete", data={"name": name})


def end_subscription(db: Session, account: User) -> None:
    """Ends the account's subscription with the payment provider straight away, so a deleted
    account isn't charged again (docs/decisions/stripe-billing.md). The subscription row goes
    with the account (ON DELETE CASCADE), but the provider's side doesn't. Nothing is refunded.

    Only here, when the deletion is carried out: 11.4 says nothing about the subscription, and
    the grace period keeps "full use of the account", so renewals carry on until then. If the
    provider can't be reached, ProviderError fails the purge job, which is retried, so the
    account isn't deleted while the provider still bills it. App Store and Google Play
    subscriptions can only be cancelled by the client in the store."""
    sub = db.scalar(
        select(Subscription).where(Subscription.account_id == account.id).with_for_update()
    )
    if sub is None or sub.status == "ended" or sub.provider in STORES:
        return
    provider = get_payment_provider()
    if sub.provider != provider.name:
        return  # e.g. a fake subscription left in a development database now on Stripe
    provider.cancel(sub.provider_subscription_id, at_period_end=False)
    audit.record(
        db,
        "billing.subscription.ended_for_deletion",
        target_type="subscription",
        target_id=sub.id,
        details={"account_id": str(account.id)},
    )


def _close_covered_requests(db: Session, account_id: uuid.UUID, deletion: DeletionRequest) -> None:
    """The account's other open requests (8.2's removals, a teen's own) are covered by this
    one, which deletes everything they would."""
    now = _now()
    db.execute(
        update(DeletionRequest)
        .where(
            DeletionRequest.account_id == account_id,
            DeletionRequest.id != deletion.id,
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        )
        .values(
            status="completed",
            completed_at=now,
            completed_by_id=deletion.completed_by_id,
            purged_at=now,
        )
    )


def _delete_account(db: Session, account: User, deletion: DeletionRequest) -> None:
    """Deletes one account: its profiles first (each with its conversations), then the row,
    which cascades to sessions, devices, acceptances, support requests, subscriptions,
    invoices, notifications, revocations and teen links. The caller holds the account's
    lock."""
    profiles = db.scalars(
        select(Profile)
        .where(Profile.account_id == account.id)
        .order_by(Profile.id)
        .with_for_update()
    ).all()
    for profile in profiles:
        purge_profile(db, account, profile)
    end_subscription(db, account)
    notifications.cancel_scheduled(db, account)
    _close_covered_requests(db, account.id, deletion)
    db.execute(delete(User).where(User.id == account.id))
    db.expunge(account)


def _purge_account(db: Session, deletion: DeletionRequest) -> list[EmailMessage]:
    """A whole account. The account row is locked first, then (for an Account Deletion) its
    invited teens' accounts, then profiles, the same order as the cascading DELETE FROM users.
    Returns the emails to send once this is committed: each invited teen's (11.4), and the
    parent's for an Invited Teen Removal."""
    account = db.get(User, deletion.account_id, with_for_update=True)
    if account is None:
        return []
    deletion.notify_email = account.email  # the address is gone with the account
    later: list[EmailMessage] = []
    if deletion.kind == "account":
        for teen_id in teens.invited_teen_accounts(db, account.id):
            teen = db.get(User, teen_id, with_for_update=True)
            if teen is None:
                continue
            later.append(emails.teen_deleted_with_parent(teen.email))
            _delete_account(db, teen, deletion)
            audit.record(
                db,
                "deletion.invited_teen_deleted",
                target_type="deletion_request",
                target_id=deletion.id,
                details={"teen_account_id": str(teen_id)},
            )
    elif deletion.kind == "teen":
        teens.remove_from_family(db, account.id)
    elif deletion.kind == "teen_removal" and deletion.requested_by_id is not None:
        parent = db.get(User, deletion.requested_by_id)
        if parent is not None:
            later.append(emails.teen_removal_complete(parent.email))
    _delete_account(db, account, deletion)
    jobs.enqueue(db, COMPLETION_EMAIL_JOB, {"deletion_request_id": str(deletion.id)})
    return later


def purge_request(db: Session, deletion_request_id: uuid.UUID) -> list[EmailMessage]:
    """Carries out one completed request (the purge job). Does nothing for a request that's
    gone back on hold, been declined, or was already purged, so it's safe to run again. Returns
    emails for the caller to send after it commits."""
    deletion = db.get(DeletionRequest, deletion_request_id, with_for_update=True)
    if deletion is None or deletion.status != "completed" or deletion.purged_at is not None:
        return []
    later: list[EmailMessage] = []
    if deletion.kind == "family_member":
        _purge_family_member(db, deletion)
    else:
        later = _purge_account(db, deletion)
    deletion.purged_at = _now()
    audit.record(
        db,
        "deletion.purged",
        target_type="deletion_request",
        target_id=deletion.id,
        details={"kind": deletion.kind},
    )
    return later


def send_completion_email(db: Session, deletion_request_id: uuid.UUID, send: SendEmail) -> None:
    """Story 11.4: "The Client receives an email once the deletion is complete." For a deleted
    account, the address kept on the request is used once, then cleared. The worker commits;
    a failed send is retried."""
    deletion = db.get(DeletionRequest, deletion_request_id, with_for_update=True)
    if deletion is None:
        return
    to = deletion.notify_email
    if to is None:
        account = db.get(User, deletion.account_id)
        if account is None:
            return
        to = account.email
    send(emails.deletion_complete(to, deletion))
    deletion.notify_email = None


def purge_deleted_conversations(db: Session, now: datetime) -> int:
    """Conversations the client deleted more than `deleted_conversation_purge_days` ago are
    deleted with their messages and feedback (escalation records stay). An account with a
    request on legal hold keeps them. A batch at a time; returns how many."""
    cutoff = now - timedelta(days=settings.deleted_conversation_purge_days)
    on_hold = select(DeletionRequest.account_id).where(DeletionRequest.status == "on_legal_hold")
    ids = db.scalars(
        select(Conversation.id)
        .join(Profile, Conversation.profile_id == Profile.id)
        .where(
            Conversation.deleted_at.is_not(None),
            Conversation.deleted_at <= cutoff,
            Profile.account_id.not_in(on_hold),
        )
        .order_by(Conversation.deleted_at)
        .limit(settings.privacy_sweep_batch_size)
        .with_for_update(of=Conversation, skip_locked=True)
    ).all()
    if not ids:
        return 0
    _delete_conversations(db, ids)
    for conversation_id in ids:
        audit.record(
            db, "conversation.purged", target_type="conversation", target_id=conversation_id
        )
    return len(ids)
