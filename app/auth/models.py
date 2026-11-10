import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PendingSignUp(Base):
    """One sign-up attempt waiting for its emailed code (story 1.1). The account is only
    created when the code is verified, and then gets this row's id; an attempt that's never
    verified is deleted once it expires (app/auth/jobs.py), so its details aren't kept.

    Each attempt is separate, even for the same email: nobody can close, lock or overwrite
    someone else's attempt, so typing someone's email can't stop them signing up."""

    __tablename__ = "pending_sign_ups"
    __table_args__ = (CheckConstraint("country = 'US'", name="ck_pending_sign_ups_country"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(index=True)  # lowercase, like users.email
    # Where the attempt came from, for the per-email-and-IP limit on code emails.
    ip_address: Mapped[str | None]
    first_name: Mapped[str]
    # Personal data, as on users (encrypted in Phase 4); deleted with the row.
    date_of_birth: Mapped[date]
    country: Mapped[str]
    state: Mapped[str]
    zip_code: Mapped[str]  # back in the 6 Nov stories
    password_hash: Mapped[str]
    # The Terms and Privacy Policy versions accepted on the form, recorded on the account.
    policy_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "subscription_plan IN ('individual', 'family')", name="ck_users_subscription_plan"
        ),
        CheckConstraint("country = 'US'", name="ck_users_country"),
        CheckConstraint("account_type IN ('adult', 'teen')", name="ck_users_account_type"),
        CheckConstraint("role IN ('client', 'admin', 'super_admin')", name="ck_users_role"),
        # Emails are stored lowercase; this also stops two accounts whose emails differ only
        # in case, whichever code path writes them (sign-up, admin invites, email changes).
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # "teen": an invited teen with their own account (story 1.5), whose access follows the
    # parent's Family plan (app/teens/). "adult" for everyone else, including a teen whose
    # account became an adult one at the age of majority (1.6, changed in place).
    account_type: Mapped[str] = mapped_column(default="adult", server_default="adult")
    email: Mapped[str] = mapped_column(unique=True)  # always stored lowercase
    first_name: Mapped[str]
    # No story collects a last name any more (docs/PLAN.md, question 32).
    last_name: Mapped[str | None]
    # Story 1.1 asks for these at sign-up. They're personal data (the date of birth is a
    # HIPAA identifier), encrypted in Phase 4. Null only for accounts made before 4 Nov.
    # They're copied from the PendingSignUp when the code is verified.
    date_of_birth: Mapped[date | None]
    country: Mapped[str | None]  # only "US" can be chosen
    state: Mapped[str | None]  # the USPS code, e.g. "CA"
    # Five digits or ZIP+4 (6 Nov stories). Null on accounts made without one: before 6 Nov,
    # a teen's own account (1.5 asks for a city instead) and a transferred profile's (11.4).
    zip_code: Mapped[str | None]
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(default="client")  # client | admin | super_admin
    status: Mapped[str] = mapped_column(default="active", server_default="active")  # or deactivated
    # Every account has a verified email: it's only created once the code is verified.
    email_verified_at: Mapped[datetime]
    failed_sign_ins: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None]
    # Set by a password reset or change. Wrong codes from before it no longer count towards
    # the code locks, so a reset really is a fresh start.
    password_changed_at: Mapped[datetime | None]
    # The trial starts when the account is created, at verification (story 1.1).
    trial_ends_at: Mapped[datetime]
    # None while on the free trial; "individual" or "family" once subscribed (story 9.1). A
    # stand-in until Phase 8 adds subscriptions (see app/billing/entitlements.py).
    subscription_plan: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VerificationChallenge(Base):
    """A 6-digit code emailed to confirm the email address (sign-up) or a new device (sign-in).
    A sign-up's code belongs to its PendingSignUp, a sign-in's to the account. When a pending
    sign-up is deleted, its right code moves to the new account and the others are left with
    no owner: closed, kept only to answer "request a new code" (story 1.1). They hold no
    personal data."""

    __tablename__ = "verification_challenges"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NULL OR pending_sign_up_id IS NULL",
            name="ck_verification_challenges_owner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    pending_sign_up_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pending_sign_ups.id", ondelete="SET NULL"), index=True
    )
    # verify_email (a sign-up; older rows may belong to an account) | sign_in
    purpose: Mapped[str]
    code_hash: Mapped[str]
    sent_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    send_count: Mapped[int] = mapped_column(default=1)
    attempts: Mapped[int] = mapped_column(default=0)
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User | None] = relationship()
    pending_sign_up: Mapped[PendingSignUp | None] = relationship()


class TrustedDevice(Base):
    """A device that passed 2FA. Signing in from it skips the code until it expires."""

    __tablename__ = "trusted_devices"
    __table_args__ = (
        CheckConstraint("platform IN ('web', 'mobile')", name="ck_trusted_devices_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Set when the device passes 2FA. Sessions made from this device's token use it, so a
    # web browser's device token can't be used to get a 30-day mobile session.
    platform: Mapped[str] = mapped_column(default="web", server_default="web")
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserSession(Base):
    """A signed-in device. The app sends the session token as `Authorization: Bearer <token>`."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("platform IN ('web', 'mobile')", name="ck_sessions_platform"),
        CheckConstraint(
            "revoked_reason IN ('session_expired', 'signed_out_inactive', 'account_deactivated')",
            name="ck_sessions_revoked_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Story 1.2 times out web sessions after 30 idle minutes and 12 hours; mobile sessions
    # last up to 30 days. Chosen at sign-in by auth.service._platform (docs/PLAN.md, R1).
    platform: Mapped[str] = mapped_column(default="web", server_default="web")
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    trusted_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trusted_devices.id", ondelete="SET NULL")
    )
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    # Why the session ended, when the client should keep seeing a particular message:
    # session_expired, signed_out_inactive or account_deactivated. Null for the rest
    # (sign-out, password changes), which get the general "signed out" message.
    revoked_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship()


class PasswordResetToken(Base):
    """The single-use token inside a password reset link."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship()
