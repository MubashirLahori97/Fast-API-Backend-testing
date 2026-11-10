import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.core.database import Base


class AdminInvitation(Base):
    """One invited Admin (Super Admin 7.1 and 7.2, Admin 1.1): the invite, then the account it
    became. It's also the Admin's row in Admin Management, from Invite pending to Deactivated,
    so the listing keeps "date added" and "who added them" after setup.

    - The token in the invite link is stored only as a SHA-256 hash. It works for 24 hours
      (`settings.admin_invite_hours`) until the setup is finished, and resending replaces it,
      so the old link stops working.
    - Setup is two steps, as Admin 1.1 says: the password is set first (kept here as an Argon2
      hash), then a 6-digit code emailed to the invite's address confirms it. Only then is the
      account created (`user_id`, `accepted_at`) and these fields cleared. Until then the same
      link can be used again ("Admin closes the page before finishing").
    - A cancelled invite (`cancelled_at`) is hidden from the listing and its link stops working.
    """

    __tablename__ = "admin_invitations"
    __table_args__ = (
        # One open invite per email (expired ones count: the Super Admin resends those).
        Index(
            "uq_admin_invitations_open_email",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND cancelled_at IS NULL"),
        ),
        # Only an accepted invite has an account. An accepted invite keeps its row when the
        # account is deleted (user_id is SET NULL), so the invite history survives.
        CheckConstraint(
            "user_id IS NULL OR accepted_at IS NOT NULL", name="ck_admin_invitations_accepted"
        ),
        CheckConstraint(
            "accepted_at IS NULL OR cancelled_at IS NULL", name="ck_admin_invitations_closed"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(index=True)  # lowercase, like users.email
    # As the Super Admin typed them; the account's own names take over after setup.
    first_name: Mapped[str]
    last_name: Mapped[str]
    # Null only if that account were ever deleted (Admins are deactivated, never deleted).
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    sent_at: Mapped[datetime]  # when the current link was emailed
    send_count: Mapped[int] = mapped_column(default=1, server_default="1")

    # The setup in progress (Admin 1.1): cleared once the account exists.
    password_hash: Mapped[str | None]
    code_hash: Mapped[str | None]
    code_sent_at: Mapped[datetime | None]
    code_expires_at: Mapped[datetime | None]
    code_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    code_send_count: Mapped[int] = mapped_column(default=0, server_default="0")

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    accepted_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    invited_by: Mapped[User | None] = relationship(foreign_keys=[invited_by_id])


# Super Admin 1.1: "There's one Super Admin account". Declared here, with the admin models,
# because it's the admin side's rule; it's an index on the users table.
Index(
    "uq_users_one_super_admin",
    User.__table__.c.role,
    unique=True,
    postgresql_where=text("role = 'super_admin'"),
)
