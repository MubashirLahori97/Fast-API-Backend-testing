import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PolicyVersion(Base):
    """One published version of the Terms, Privacy Policy or Health Consent (story 13.2)."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("kind", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str]  # terms | privacy | health_consent
    version: Mapped[str]
    title: Mapped[str]  # shown in messages, e.g. "Terms of Service"
    url: Mapped[str | None]  # the full document; managed by The Oracle's team
    published_at: Mapped[datetime]


class PolicyAcceptance(Base):
    __tablename__ = "policy_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "policy_version_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_versions.id"))
    accepted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    policy_version: Mapped[PolicyVersion] = relationship()


# Deletion requests that are still open: neither carried out nor declined. In "grace_period"
# (the first 10 days) everything stays fully usable and the team can't complete it yet.
OPEN_DELETION_STATUSES = ("grace_period", "pending", "in_progress", "on_legal_hold")
# Past the grace period: the account (or the family member's profile) is locked, and the
# request is with the support team.
LOCKED_DELETION_STATUSES = ("pending", "in_progress", "on_legal_hold")
# Kinds that delete a whole account (`profile_id` is null for them).
ACCOUNT_DELETION_KINDS = ("account", "teen_removal", "teen")


class DeletionRequest(Base):
    """A request to delete data (stories 8.2 and 11.4, Super Admin 5.2). Kinds, as the team's
    list names them:

    - family_member: a Family Member Deletion, when a client removes a managed family member
      (8.2). `profile_id` is the member;
    - account: an Account Deletion (11.4): the client's account, every managed family member,
      and the accounts and data of the client's invited teens;
    - teen_removal: an Invited Teen Removal, when a parent removes an invited teen who has
      joined (8.2). `account_id` is the teen's account and `requested_by_id` the parent;
    - teen: a Teen Deletion, asked for by a teen with their own account, in the app or (when
      they can't sign in) by email to the team.

    The timeline (Super Admin 5.2): the request is acknowledged straight away and starts a
    10-day grace period (`grace_period`, until `grace_ends_at`) with full use. Then the privacy
    sweep locks the account or profile and sets `pending` (Pending review), and the team is
    told. The team completes it within 45 calendar days of the request (`due_at`); the purge job
    then deletes the data (app/privacy/purge.py). A teen's request by email has no grace period.

    Plain ids with no foreign keys, like the audit log, so the record outlives the data it
    asked to delete and the client can be told when it's done. It holds no names or health
    data; `notify_email` holds the address to tell once an account is gone, only until that
    email is sent."""

    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('family_member', 'account', 'teen_removal', 'teen')",
            name="ck_deletion_requests_kind",
        ),
        CheckConstraint(
            "status IN ('grace_period', 'pending', 'in_progress', 'on_legal_hold', "
            "'completed', 'declined')",
            name="ck_deletion_requests_status",
        ),
        CheckConstraint("source IN ('in_app', 'by_email')", name="ck_deletion_requests_source"),
        # Only a family member's deletion names a profile; the others are a whole account.
        CheckConstraint(
            "(profile_id IS NOT NULL) = (kind = 'family_member')",
            name="ck_deletion_requests_profile",
        ),
        # An invited teen's removal records the parent who removed them.
        CheckConstraint(
            "(requested_by_id IS NOT NULL) = (kind = 'teen_removal')",
            name="ck_deletion_requests_requested_by",
        ),
        CheckConstraint(
            "status <> 'grace_period' OR grace_ends_at IS NOT NULL",
            name="ck_deletion_requests_grace",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_deletion_requests_completed_at",
        ),
        CheckConstraint(
            "purged_at IS NULL OR status = 'completed'", name="ck_deletion_requests_purged"
        ),
        # One open request per family member...
        Index(
            "uq_deletion_requests_one_open_per_profile",
            "profile_id",
            unique=True,
            postgresql_where=text(
                "status IN ('grace_period', 'pending', 'in_progress', 'on_legal_hold')"
            ),
        ),
        # ...and one open request to delete a whole account.
        Index(
            "uq_deletion_requests_one_open_account",
            "account_id",
            unique=True,
            postgresql_where=text(
                "profile_id IS NULL AND status IN "
                "('grace_period', 'pending', 'in_progress', 'on_legal_hold')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The account whose data goes: the client's, or the teen's for teen_removal and teen.
    account_id: Mapped[uuid.UUID] = mapped_column(index=True)
    profile_id: Mapped[uuid.UUID | None]  # family_member only
    kind: Mapped[str]  # family_member | account | teen_removal | teen
    # teen_removal: the parent who removed the teen (a plain id, like account_id).
    requested_by_id: Mapped[uuid.UUID | None]
    # Super Admin 5.2: in_app, or by_email (created by the team for a teen who can't sign in).
    source: Mapped[str] = mapped_column(default="in_app", server_default="in_app")
    # Super Admin 5.2: grace_period, pending (review), in_progress, on_legal_hold, completed.
    # declined: the team turned it down, and the data is back in use.
    status: Mapped[str] = mapped_column(default="pending", server_default="pending", index=True)
    requested_at: Mapped[datetime]
    # The end of the 10-day grace period; null for a teen's request by email (none).
    grace_ends_at: Mapped[datetime | None]
    # When the "deleted tomorrow" reminder went (12.1), so it goes once.
    grace_reminded_at: Mapped[datetime | None]
    # When the grace period ended and the account or profile was locked.
    locked_at: Mapped[datetime | None]
    # The deadline: 45 calendar days after the request (CCPA/CPRA), or after the day a teen's
    # email was received.
    due_at: Mapped[datetime]
    # When the support team was emailed about it (app/privacy/jobs.py), once it's ready for
    # review.
    team_notified_at: Mapped[datetime | None]
    legal_hold_at: Mapped[datetime | None]  # set while it's on legal hold
    # The team's side: who created a by-email request, and who completed it.
    created_by_id: Mapped[uuid.UUID | None]
    completed_by_id: Mapped[uuid.UUID | None]
    # The team marked it completed; the purge job then deletes the data and sets purged_at.
    completed_at: Mapped[datetime | None]
    purged_at: Mapped[datetime | None]
    # Where to send "your deletion is complete" once the account itself is gone. Set by the
    # purge, cleared as soon as the email is sent.
    notify_email: Mapped[str | None]


class ConsentRevocation(Base):
    """Story 11.4: the client revoked their consent. While a row has no `restored_at`, they
    can only use Privacy & Data; the Oracle, analytics and notifications don't use their
    information, and their invited teens are paused. Nothing is deleted. Accepting the Terms of
    Service, Privacy Policy and Health Consent again sets `restored_at`. Rows are kept as the
    history, and the audit log records both steps."""

    __tablename__ = "consent_revocations"
    __table_args__ = (
        Index(
            "uq_consent_revocations_one_open_per_account",
            "account_id",
            unique=True,
            postgresql_where=text("restored_at IS NULL"),
        ),
        CheckConstraint(
            "restored_at IS NULL OR restored_at >= revoked_at",
            name="ck_consent_revocations_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    revoked_at: Mapped[datetime]
    restored_at: Mapped[datetime | None]
