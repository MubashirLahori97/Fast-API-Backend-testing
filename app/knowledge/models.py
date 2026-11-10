import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, UniqueConstraint, func
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Super Admin 6.1's content types, in its order.
CONTENT_TYPES = (
    "book",
    "protocol",
    "blog_post",
    "qa_answer",
    "symptom_chart",
    "diagnostic_tree",
    "case_study",
    "knowledge_gap_answer",
)
# 6.3's statuses. answer_pending: an Admin's answer is waiting for the Super Admin's approval.
GAP_STATUSES = ("new", "answer_pending", "answered", "dismissed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class KnowledgeFile(Base):
    """A file uploaded for the knowledge base (Super Admin 6.2): a PDF, Word (DOCX) or text
    file. Kept in the database for now, as "the app's own library"; production moves the bytes
    to Azure storage behind the same table. The content is Deborah's public material, not health
    data. Never deleted: a version that used it keeps it."""

    __tablename__ = "knowledge_files"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', "
            "'text/plain')",
            name="ck_knowledge_files_media_type",
        ),
        CheckConstraint("size_bytes > 0", name="ck_knowledge_files_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]  # the uploaded file's name, cleaned
    media_type: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str]
    # Loaded only when asked for, so lists and details don't read the whole file.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KnowledgeGap(Base):
    """A question the Oracle couldn't answer (Super Admin 6.3), made from the Knowledge Gap
    support requests (app/support/), with similar questions grouped into one gap.

    `question` is the first client's own words, so it's treated as health data: never logged,
    audited, emailed or put in a job payload. A gap never says who asked: the client's details
    stay in the linked support requests (KnowledgeGapRequest).

    Statuses (6.3, 6 Nov 19:22): new; answer_pending (an Admin sent an answer, waiting for the
    Super Admin); answered (content linked to it was published); dismissed (with a reason). A
    rejected Admin answer sends the gap back to new, with the reason on the answer."""

    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        CheckConstraint(_in("status", GAP_STATUSES), name="ck_knowledge_gaps_status"),
        CheckConstraint("times_asked >= 1", name="ck_knowledge_gaps_times_asked"),
        CheckConstraint(
            "(status = 'dismissed') = (dismissed_at IS NOT NULL)",
            name="ck_knowledge_gaps_dismissed_at",
        ),
        CheckConstraint(
            "(status = 'answered') = (answered_at IS NOT NULL)",
            name="ck_knowledge_gaps_answered_at",
        ),
        # 6.3's listing: new gaps first, most asked first.
        Index("ix_knowledge_gaps_status_times_asked", "status", "times_asked"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question: Mapped[str]
    topic: Mapped[str | None]  # the Oracle's, e.g. "Sleep" or "Thyroid"
    status: Mapped[str] = mapped_column(default="new", server_default="new")
    # Similar questions grouped into this gap, counting the first.
    times_asked: Mapped[int] = mapped_column(default=1, server_default="1")
    first_asked_at: Mapped[datetime]
    last_asked_at: Mapped[datetime]
    dismissed_reason: Mapped[str | None]
    dismissed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    dismissed_at: Mapped[datetime | None]
    answered_at: Mapped[datetime | None]
    # The content that answers it: an Admin's answer waiting for approval, the published answer,
    # or an Admin's rejected answer (its version holds the Super Admin's reason).
    answer_content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_contents.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class KnowledgeGapRequest(Base):
    """Which Knowledge Gap support request went into which gap. Deleted with the request (and
    so with the client's account); the gap's count stays."""

    __tablename__ = "knowledge_gap_requests"

    support_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_requests.id", ondelete="CASCADE"), primary_key=True
    )
    gap_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_gaps.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KnowledgeContent(Base):
    """One item of the knowledge base (Super Admin 6.1 and 6.2): a book, protocol, blog post,
    Q&A answer, symptom chart, diagnostic tree, case study or knowledge gap answer. Its text is
    in KnowledgeContentVersion; content is archived, never deleted, so every version can be
    traced.

    - `latest_version`: the newest version, which the listing shows (its title and type are
      copied here). A draft or a version waiting for approval is edited in place; any other
      save adds a version.
    - `published_version`: the version the Oracle uses, unless the item is archived. An Admin's
      edit waits for approval while the Oracle keeps using the published version.
    - `status`: what the listing shows. Archived, or the latest version's status: draft,
      pending_approval, published or rejected. Rejected items stay in the listing.

    Every change to what the Oracle uses is given to it in the same request, before the commit
    (app/knowledge/service.py's `deliver`). Nothing is synced automatically (6.2, 6 Nov 19:22):
    all content, blog posts included, is added through Add New Content."""

    __tablename__ = "knowledge_contents"
    __table_args__ = (
        CheckConstraint(_in("content_type", CONTENT_TYPES), name="ck_knowledge_contents_type"),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'published', 'rejected', 'archived')",
            name="ck_knowledge_contents_status",
        ),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="ck_knowledge_contents_archived_at",
        ),
        CheckConstraint(
            "published_version IS NULL OR published_version <= latest_version",
            name="ck_knowledge_contents_published_version",
        ),
        # 6.1's listing: pending approval first, then newest first.
        Index("ix_knowledge_contents_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str]
    content_type: Mapped[str]
    status: Mapped[str]
    latest_version: Mapped[int] = mapped_column(default=1, server_default="1")
    published_version: Mapped[int | None]
    # 6.2 and 6.3: the gap this content answers, when it was added from one.
    knowledge_gap_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_gaps.id", ondelete="SET NULL"), index=True
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["KnowledgeContentVersion"]] = relationship(
        back_populates="content", order_by="KnowledgeContentVersion.number"
    )
    knowledge_gap: Mapped[KnowledgeGap | None] = relationship(foreign_keys=[knowledge_gap_id])


class KnowledgeContentVersion(Base):
    """One version of an item (6.1's version history). Statuses:

    - draft: saved, not used by the Oracle (6.2);
    - pending_approval: an Admin's save, waiting for the Super Admin;
    - published: approved and published at `published_at` (it stays "published" in the history
      after a newer version replaces it);
    - rejected: the Super Admin turned it down, with `rejection_reason`;
    - superseded: a draft or pending version left behind by a roll back.

    A version has typed text, an uploaded file, or both."""

    __tablename__ = "knowledge_content_versions"
    __table_args__ = (
        UniqueConstraint("content_id", "number"),
        CheckConstraint(_in("content_type", CONTENT_TYPES), name="ck_knowledge_versions_type"),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'published', 'rejected', 'superseded')",
            name="ck_knowledge_versions_status",
        ),
        CheckConstraint(
            "text IS NOT NULL OR file_id IS NOT NULL", name="ck_knowledge_versions_content"
        ),
        CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name="ck_knowledge_versions_rejection_reason",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_knowledge_versions_published_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_contents.id", ondelete="CASCADE")
    )
    number: Mapped[int]
    title: Mapped[str]
    content_type: Mapped[str]
    text: Mapped[str | None] = mapped_column(deferred=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="RESTRICT")
    )
    status: Mapped[str]
    rejection_reason: Mapped[str | None]
    # A roll back publishes a copy of an earlier version as a new one.
    rolled_back_from: Mapped[int | None]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Who approved or rejected it, and when.
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=sql("clock_timestamp()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    content: Mapped[KnowledgeContent] = relationship(back_populates="versions")
    file: Mapped[KnowledgeFile | None] = relationship()
