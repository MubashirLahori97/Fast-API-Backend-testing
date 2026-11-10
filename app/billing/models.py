import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subscription(Base):
    """The account's paid subscription (stories 9.1 and 11.3). One row per account, reused
    when they subscribe again; no row means they've never subscribed, so they're on the free
    trial (app/billing/entitlements.py). Subscription and payment events are in the audit log.

    Statuses:

    - active: paid, and renews at current_period_end;
    - past_due: a payment failed ("Payment issue"); access continues until grace_ends_at;
    - cancelled: the client cancelled ("Cancelled"); access continues until the end of the
      period paid for, or of the grace period if a payment had failed, and then it ends;
    - ended: no access. ended_reason says why: cancelled, payment_failed, or other (the
      provider ended it).

    Changes the client asks for from the next billing date wait in pending_plan (a downgrade
    to Individual) until the period ends. Add-ons follow the places in use: at each period end,
    any the client no longer needs are dropped (settled_period_end records it's been done).

    No card details: only the brand and last 4 digits, for "Visa ending 4417"."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('fake', 'stripe', 'app_store', 'google_play')",
            name="ck_subscriptions_provider",
        ),
        CheckConstraint("plan IN ('individual', 'family')", name="ck_subscriptions_plan"),
        CheckConstraint(
            "pending_plan IN ('individual', 'family')", name="ck_subscriptions_pending_plan"
        ),
        CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled', 'ended')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "ended_reason IN ('cancelled', 'payment_failed', 'other')",
            name="ck_subscriptions_ended_reason",
        ),
        CheckConstraint("add_on_members >= 0", name="ck_subscriptions_add_on_members"),
        CheckConstraint(
            "plan = 'family' OR add_on_members = 0", name="ck_subscriptions_add_ons_family"
        ),
        CheckConstraint(
            "(status = 'ended') = (ended_at IS NOT NULL)", name="ck_subscriptions_ended_at"
        ),
        CheckConstraint(
            "status <> 'past_due' OR grace_ends_at IS NOT NULL", name="ck_subscriptions_grace"
        ),
        CheckConstraint(
            "status <> 'cancelled' OR cancel_at_period_end", name="ck_subscriptions_cancelled"
        ),
        UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_subscriptions_provider_subscription"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str]  # app.billing.provider.ProviderName
    provider_customer_id: Mapped[str | None]
    provider_subscription_id: Mapped[str]
    plan: Mapped[str]
    status: Mapped[str]
    # What this period is billed at, so a price change in the admin panel reaches existing
    # subscribers only from their next billing date (Super Admin story 8.1).
    plan_price_cents: Mapped[int]
    add_on_price_cents: Mapped[int]
    currency: Mapped[str]
    # Family plan places beyond settings.family_members_included.
    add_on_members: Mapped[int] = mapped_column(default=0, server_default="0")
    pending_plan: Mapped[str | None]
    current_period_start: Mapped[datetime]
    current_period_end: Mapped[datetime]
    settled_period_end: Mapped[datetime | None]
    # Mirrors the provider's flag: true from Cancel until Resume (and after the end it led to).
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False, server_default="false")
    cancelled_at: Mapped[datetime | None]
    # Set while a failed payment is waiting to be fixed (settings.payment_grace_days).
    grace_ends_at: Mapped[datetime | None]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    ended_reason: Mapped[str | None]
    payment_method_brand: Mapped[str | None]
    payment_method_last4: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Invoice(Base):
    """One payment, or a payment that failed: the billing history and its receipts (story
    11.3). The amount, date and status only, never card details. Kept for as long as the
    account is."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("status IN ('paid', 'failed')", name="ck_invoices_status"),
        CheckConstraint("amount_cents >= 0", name="ck_invoices_amount"),
        UniqueConstraint("provider", "provider_invoice_id", name="uq_invoices_provider_invoice"),
        Index("ix_invoices_account_issued", "account_id", "issued_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]
    provider_invoice_id: Mapped[str]
    plan: Mapped[str | None]  # the plan it paid for, when known
    amount_cents: Mapped[int]
    currency: Mapped[str]
    status: Mapped[str]
    issued_at: Mapped[datetime]
    receipt_url: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PaymentEvent(Base):
    """A provider webhook already handled, so one delivered twice is handled once. Only its id
    and type are kept: the event's content stays with the provider."""

    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str]
    event_id: Mapped[str]
    type: Mapped[str]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PausedFamilyMember(Base):
    """A family member the system turned off because the Family plan ended (story 11.3), so
    they can be turned back on when it's active again. Members the client turned off
    themselves aren't here. `turned_off_at` is the profile's own value from that turn-off:
    if the client turns the member on and off again later, the times differ, and the system
    leaves the member alone."""

    __tablename__ = "paused_family_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True
    )
    turned_off_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
