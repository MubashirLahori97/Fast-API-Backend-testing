import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PolicyText(Base):
    """The text of a policy version, and its summary of changes (Super Admin 9.1 and 9.2).

    A draft of the next version (at most one per policy) is edited freely. Once published it
    becomes the text of the `policy_versions` row with the same kind and version, and can never
    change again, so there's always a record of exactly what each client agreed to. The 1.0
    versions seeded before the admin panel existed have no text here (their `url` points to the
    document).

    The text is public (the policies clients read), not health data."""

    __tablename__ = "policy_texts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('terms', 'privacy', 'health_consent')", name="ck_policy_texts_kind"
        ),
        CheckConstraint("status IN ('draft', 'published')", name="ck_policy_texts_status"),
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name="ck_policy_texts_published_at",
        ),
        UniqueConstraint("kind", "version"),
        Index(
            "uq_policy_texts_one_draft",
            "kind",
            unique=True,
            postgresql_where=sql("status = 'draft'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str]  # terms | privacy | health_consent
    # Set automatically (9.2): the live version with its last number raised, e.g. 1.0 to 1.1.
    # A draft's is worked out again when it's published.
    version: Mapped[str]
    text: Mapped[str] = mapped_column(default="", server_default="", deferred=True)
    summary_of_changes: Mapped[str] = mapped_column(default="", server_default="")
    status: Mapped[str] = mapped_column(default="draft", server_default="draft")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
