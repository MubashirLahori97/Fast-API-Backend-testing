import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, object_session

from app.auth.models import User
from app.core.database import Base


class Profile(Base):
    """A person the Oracle helps: the client themself, or a family member they manage
    (stories 2.1 and 2.2). Family members have no login; the account holder acts for them.

    Everything about the person is sensitive: date of birth, sex at birth, gender identity,
    pronouns and the write-ins, and for family members also their first name, relationship and
    advocate consent. These are stored in plain text until Phase 4 adds field encryption
    (docs/PLAN.md). Admin tools, exports and the Oracle's context must pick fields explicitly,
    never serialize whole rows: the advocate consent option is never shown to the support team.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        # An account has at most one "myself" profile...
        Index(
            "uq_profiles_one_self_per_account",
            "account_id",
            unique=True,
            postgresql_where=text("is_self"),
        ),
        # ...and at most one unfinished family draft at a time.
        Index(
            "uq_profiles_one_family_draft_per_account",
            "account_id",
            unique=True,
            postgresql_where=text("NOT is_self AND intake_completed_at IS NULL"),
        ),
        # The consent option and its time are always set (or cleared) together.
        CheckConstraint(
            "(advocate_consent IS NULL) = (advocate_consent_at IS NULL)",
            name="ck_profiles_advocate_consent_pair",
        ),
        # Only a finished family member can be turned off or have their deletion requested.
        CheckConstraint(
            "turned_off_at IS NULL OR intake_completed_at IS NOT NULL",
            name="ck_profiles_turned_off_after_intake",
        ),
        CheckConstraint("NOT is_self OR turned_off_at IS NULL", name="ck_profiles_self_stays_on"),
        CheckConstraint(
            "deletion_requested_at IS NULL OR intake_completed_at IS NOT NULL",
            name="ck_profiles_deletion_request_after_intake",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    is_self: Mapped[bool]
    # Family members only (story 2.2). The client's own name lives on the users row.
    first_name: Mapped[str | None]
    # The codes for this and the other choices are in options.py.
    family_relationship: Mapped[str | None]  # parent | child | partner | someone_else

    # The client's own is copied from users.date_of_birth (sign-up) when the profile is created,
    # and can't be changed here. A family member's is asked in their intake (story 2.2).
    date_of_birth: Mapped[date | None]
    # Family members aged 13 up to the age of majority only (story 2.2's Teen Profile Choice):
    # "managed" (the client manages the profile). "own_account" (an invited teen) comes with
    # Phase 3b.
    teen_profile_choice: Mapped[str | None]
    # Family members only: how the client may act for them (story 2.2 step 4), and when they
    # confirmed it. Never shown to the support team.
    advocate_consent: Mapped[str | None]
    advocate_consent_at: Mapped[datetime | None]
    sex_at_birth: Mapped[str | None]  # male | female | intersex | prefer_not_to_say
    # woman | man | non_binary | agender | not_listed | prefer_not_to_say
    gender_identity: Mapped[str | None]
    gender_identity_other: Mapped[str | None]  # the write-in when gender_identity is "not_listed"
    pronouns: Mapped[str | None]  # he_him | she_her | they_them | other
    pronouns_other: Mapped[str | None]  # the write-in when pronouns is "other"
    intake_completed_at: Mapped[datetime | None]
    # Story 8.2. A turned-off family member keeps their information, but is hidden from the
    # profile panel, can't be used, and gives up their place in the plan's limit.
    turned_off_at: Mapped[datetime | None]
    # Story 8.2. A pending deletion request (see accounts.models.DeletionRequest). Until the
    # team completes it the member can't be changed or used for new conversations, but stays
    # where they are and keeps their place, as the story describes.
    deletion_requested_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    @property
    def majority_state(self) -> str | None:
        """The state whose age of majority counts for this profile (app/core/ages.py): the
        account's state. For the client's own profile and a teen's own account that's their
        own; for a family member it's the account holder's, an assumption (the stories don't
        say: docs/decisions/state-age-of-majority.md). The account comes from the session's
        identity map when it's already loaded (the signed-in user usually is). None (so 18)
        for a profile outside a session."""
        session = object_session(self)
        account = session.get(User, self.account_id) if session is not None else None
        return account.state if account is not None else None
