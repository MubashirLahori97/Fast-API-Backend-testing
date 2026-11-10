"""Client Details' health profile (Super Admin and Admin 3.1, 6 Nov 19:22): the client's own
health profile, read-only, for the Super Admin and Admins, including teens with their own
account. Conversations, guidance summaries, provider notes and visit logs aren't shown.

It's read through app/health/service.py's `health_profile_out`, the same view the client gets in
My Health, without the parts that are only for editing: the About you fields that can be
edited, the suggested answers (`prefill`) and the conversation an answer came from. It's health
data: never logged, and the view's audit event (`admin.client_viewed`) says only whether one was
shown.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.clients.schemas import HealthProfileView
from app.auth.models import User
from app.health import service as health
from app.health.schemas import QuestionOut, SectionOut
from app.profiles.models import Profile


def _read_only(question: QuestionOut) -> QuestionOut:
    answer = question.answer
    if answer is not None:
        answer = answer.model_copy(update={"conversation_id": None})
    return question.model_copy(update={"answer": answer, "prefill": None})


def health_profile(db: Session, account: User) -> HealthProfileView | None:
    """The account's own profile's health profile, or None when it has none yet (no date of
    birth, so no questions apply)."""
    profile = db.scalar(
        select(Profile).where(Profile.account_id == account.id, Profile.is_self).limit(1)
    )
    if profile is None or profile.date_of_birth is None:
        return None
    full = health.health_profile_out(db, profile, account)
    return HealthProfileView(
        profile_id=full.profile_id,
        completion=full.completion,
        complete=full.complete,
        about_you=full.about_you.model_copy(update={"editable": []}),
        sections=[
            SectionOut(
                key=section.key,
                title=section.title,
                privacy_notice=section.privacy_notice,
                questions=[_read_only(question) for question in section.questions],
            )
            for section in full.sections
        ],
        question_bank_version=full.question_bank_version,
    )
