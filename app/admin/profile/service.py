"""My Profile (Super Admin 12.1, Admin 8.1): the first and last name only; the email can't be
changed here (an Admin with a new address is deactivated and invited again, Super Admin 7.1).
Every change is audited."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.profile.schemas import AdminProfileEdit, AdminProfileOut
from app.auth.models import UserSession
from app.core import audit
from app.core.errors import AppError, database_errors_retryable

# Super Admin 12.1's message.
PROFILE_UPDATED = "Your profile has been updated."
# Not in the stories (docs/decisions/phase-a1-admin-access.md). 12.1: Admins' new addresses
# come from a new invite, the Super Admin's from Tkxel.
EMAIL_LOCKED = "Your email address can’t be changed here."


def my_profile(db: Session, session: UserSession) -> AdminProfileOut:
    user = session.user
    previous = db.scalar(
        select(UserSession.created_at)
        .where(UserSession.user_id == user.id, UserSession.created_at < session.created_at)
        .order_by(UserSession.created_at.desc())
        .limit(1)
    )
    return AdminProfileOut(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name or "",
        email=user.email,
        role=user.role,
        signed_in_at=session.created_at,
        previous_sign_in_at=previous,
    )


def update_my_profile(
    db: Session, session: UserSession, edit: AdminProfileEdit, request: Request
) -> AdminProfileOut:
    """12.1's Edit and Save: the first and last name only."""
    user = session.user
    if edit.email is not None and edit.email.strip().lower() != user.email:
        raise AppError(422, "email_locked", EMAIL_LOCKED, "email")
    with database_errors_retryable(db):
        db.refresh(user, with_for_update=True)
        changed = [
            field
            for field in ("first_name", "last_name")
            if getattr(user, field) != getattr(edit, field)
        ]
        for field in changed:
            setattr(user, field, getattr(edit, field))
        if changed:
            audit.record(
                db,
                "admin.profile_updated",
                actor_id=user.id,
                target_type="user",
                target_id=user.id,
                request=request,
                details={"fields": changed},
            )
        db.commit()
    return my_profile(db, session)
