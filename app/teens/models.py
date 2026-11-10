import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeenLink(Base):
    """The parent's side of an invited teen (stories 1.5, 8.1 and 8.2): only what the parent
    entered (the teen's first name, who they are to the parent, the email the invite went to)
    and the link's state. The teen's account, profile, conversations and health information are
    the teen's own (users.account_type = 'teen'), so nothing here is the teen's health or
    activity, and OwnedProfile keeps the parent out of the teen's profile.

    - An invite until the teen joins (`teen_account_id` and `joined_at` set). It takes one of the
      parent's family places from the moment it's sent (8.1), until it's turned off or removed.
    - Turned off (`turned_off_at`): the place is freed and the teen sees only Privacy & Data.
    - Removed: the row is deleted. The place is freed; the teen's account and data stay, and the
      teen sees only Privacy & Data (8.2). It's also deleted when the teen moves to an adult
      account (1.6) or their own deletion is completed (11.4).

    The invite token is in the link's `#` fragment and stored only as its SHA-256 hash. A resend
    replaces it, and joining clears it, so a link works once (1.5)."""

    __tablename__ = "teen_links"
    __table_args__ = (
        # One link per email for each parent: a second invite is a resend.
        UniqueConstraint("parent_account_id", "email", name="uq_teen_links_parent_email"),
        CheckConstraint(
            "(teen_account_id IS NULL) = (joined_at IS NULL)", name="ck_teen_links_joined"
        ),
        # A used invite has no token left.
        CheckConstraint(
            "teen_account_id IS NULL OR token_hash IS NULL", name="ck_teen_links_token_used"
        ),
        CheckConstraint(
            "teen_account_id IS NULL OR teen_account_id <> parent_account_id",
            name="ck_teen_links_not_self",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The teen's own account, once they've joined. One link per teen account.
    teen_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # What the parent typed in the family intake (story 2.2 steps 1 and 2). Personal data, shown
    # only to the parent, and used for [Name] in the parent's notices.
    first_name: Mapped[str]
    family_relationship: Mapped[str]  # app/profiles/options.py: parent | child | partner | ...
    email: Mapped[str]  # lowercase, like users.email; the teen's account uses it
    token_hash: Mapped[str | None] = mapped_column(unique=True)
    invite_sent_at: Mapped[datetime]
    invite_expires_at: Mapped[datetime]
    joined_at: Mapped[datetime | None]
    turned_off_at: Mapped[datetime | None]
    # Set when the end of the parent's Family plan paused this teen (11.3), and cleared when the
    # plan is active again, so the parent's paused and restored notices go once each. The access
    # gate doesn't read it: it checks the plan itself (app/teens/access.py).
    plan_paused_at: Mapped[datetime | None]
    # The Health Consent version the parent gave for this teen (stories 3.1 and 12.2): at the
    # invite, and again for each updated version. Until it's the current one, the teen is paused.
    health_consent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_versions.id"))
    health_consent_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TeenAccount(Base):
    """The teen's own details that adult accounts don't have (story 1.5's About You), and the
    age-of-majority bookkeeping (1.6). One row per account with `account_type = 'teen'`; it's
    deleted when the account becomes an adult one, and with the account."""

    __tablename__ = "teen_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Personal data (a place smaller than a state is a HIPAA identifier). Collected by 1.5; not
    # used yet (docs/decisions/phase-3b-teens.md).
    city: Mapped[str]
    joined_at: Mapped[datetime]
    # 1.6: the two-week reminder was handed to notifications.schedule, once.
    reminder_scheduled_at: Mapped[datetime | None]
    # 1.6: the daily check found the teen at the age of majority and recorded that the teen
    # account stopped (audited once). The gate itself works from the date of birth.
    aged_out_at: Mapped[datetime | None]


class TeenParentNotice(Base):
    """Story 3.2: the parent was told that their teen may need help after an emergency or a
    crisis. Super Admin 4.1 shows when. Plain ids, like the escalation it's about, so it's kept
    as long as the escalation; no names, levels or content."""

    __tablename__ = "teen_parent_notices"

    escalation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    told_at: Mapped[datetime]
