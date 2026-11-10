import uuid
from typing import Annotated

from fastapi import Depends

from app.accounts.dependencies import ClientSession
from app.core.database import DbSession
from app.profiles.models import Profile
from app.visits.models import VisitLog
from app.visits.service import visit_log_not_found


def owned_visit_log(visit_log_id: uuid.UUID, session: ClientSession, db: DbSession) -> VisitLog:
    """The visit log in the URL, if its profile belongs to the signed-in account. Any other log,
    including a teen's own seen from the parent's account, gets the same 404, so ids can't be
    probed."""
    log = db.get(VisitLog, visit_log_id)
    if log is not None:
        profile = db.get(Profile, log.profile_id)
        if profile is not None and profile.account_id == session.user_id:
            return log
    raise visit_log_not_found()


OwnedVisitLog = Annotated[VisitLog, Depends(owned_visit_log)]
