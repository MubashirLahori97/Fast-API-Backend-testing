"""What the Oracle is given about a profile for the visit review (5.2) and the Wellness Plan
(7.1): the conversations' ProfileContext, with the health profile filled in, so new medicines
are checked against the ones already taken. Fields are picked one by one, never whole rows.
"""

from dataclasses import replace

from sqlalchemy.orm import Session

from app.auth.models import User
from app.conversations import service as conversations
from app.health import service as health
from app.oracle import contract
from app.profiles.models import Profile


def health_context(db: Session, profile: Profile, account: User) -> contract.HealthContext:
    """The answered questions that apply to the profile now (story 6.1)."""
    return contract.HealthContext(
        answered=tuple(
            contract.HealthAnswer(
                key=known.key,
                section=known.section,
                question=known.question,
                answer=known.answer,
                value=known.value,
                other=known.other,
                sensitive=known.sensitive,
                from_conversation=known.from_conversation,
                updated_at=known.updated_at,
            )
            for known in health.health_context(db, profile, account)
        )
    )


def oracle_context(db: Session, profile: Profile, account: User) -> contract.ProfileContext:
    context = conversations.profile_context(profile, account)
    return replace(context, health=health_context(db, profile, account))
