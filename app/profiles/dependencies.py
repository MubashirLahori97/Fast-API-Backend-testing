import uuid
from typing import Annotated

from fastapi import Depends

from app.accounts.dependencies import ClientSession
from app.core.database import DbSession
from app.core.errors import AppError
from app.profiles import service
from app.profiles.models import Profile


def owned_profile(profile_id: uuid.UUID, session: ClientSession, db: DbSession) -> Profile:
    """The profile in the URL, if it belongs to the signed-in account. Any other profile,
    including one that doesn't exist, gets the same 404, so ids can't be probed."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.account_id != session.user_id:
        raise AppError(404, "profile_not_found", "We couldn’t find that profile.")
    return profile


OwnedProfile = Annotated[Profile, Depends(owned_profile)]


def usable_profile(profile: OwnedProfile) -> Profile:
    """An owned profile that can be used: its intake is finished, and it isn't turned off or
    being deleted. Conversations, and anything else that uses a profile, take this."""
    service.check_can_use(profile)
    return profile


UsableProfile = Annotated[Profile, Depends(usable_profile)]
