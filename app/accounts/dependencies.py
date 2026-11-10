from typing import Annotated

from fastapi import Depends

from app.accounts.service import (
    BEING_DELETED,
    CONSENT_NEEDED,
    consent_revoked,
    deletion_locked,
    pending_policies,
)
from app.auth.dependencies import BackgroundSession, CurrentSession
from app.auth.models import UserSession
from app.core.database import DbSession
from app.core.errors import AppError
from app.privacy import teens


def consented_session(session: CurrentSession, db: DbSession) -> UserSession:
    """A signed-in session whose client may use the app: the policy gate.

    Refused, in this order:

    - an Admin or the Super Admin: the client app is for clients;
    - the account is locked for deletion, after its grace period (stories 1.2 and 11.4): its own
      request, or for an invited teen the parent's Account Deletion. During the grace period
      everything works as normal;
    - a teen account whose owner has reached the age of majority (story 1.6): only Privacy &
      Data and Create My Account (/me/adult-account);
    - an invited teen who has lost access (stories 1.5, 8.2, 11.4, 12.2): only Privacy & Data;
    - consent was revoked (story 11.4) and not given again: the client accepts the Terms of
      Service, Privacy Policy and Health Consent first;
    - updated policies aren't accepted yet (story 12.2).

    Use ClientSession on every profile and health endpoint. Only the endpoints that let a
    client accept the policies (and /me, sign-out) use CurrentSession, and Privacy & Data uses
    PrivacySession."""
    user = session.user
    if user.role != "client":
        # The admin panel's accounts never use the client app, so no health data can end up
        # on an admin account (not in the stories; docs/decisions/phase-a1-admin-access.md).
        raise AppError(403, "clients_only", "This part of the app is for clients.")
    if deletion_locked(db, user):
        raise AppError(403, "account_being_deleted", BEING_DELETED)
    if teens.age_of_majority_reached(db, user):
        raise AppError(403, "age_of_majority_reached", teens.AGE_OF_MAJORITY_REACHED)
    if teens.access_paused(db, user):
        raise AppError(403, "access_paused", teens.ACCESS_PAUSED)
    if consent_revoked(db, user):
        raise AppError(403, "consent_revoked", CONSENT_NEEDED)
    if pending_policies(db, user):
        raise AppError(
            403,
            "policy_update_required",
            "Please review and accept the updated policies to continue.",
        )
    return session


ClientSession = Annotated[UserSession, Depends(consented_session)]


def consented_background_session(session: BackgroundSession, db: DbSession) -> UserSession:
    """ClientSession for requests the app makes by itself: they don't count as activity."""
    return consented_session(session, db)


ClientBackgroundSession = Annotated[UserSession, Depends(consented_background_session)]


def privacy_session(session: CurrentSession, db: DbSession) -> UserSession:
    """Story 11.4: Privacy & Data stays open when nothing else does. A client who revoked
    consent or hasn't accepted updated policies, an account in a deletion's grace period, and an
    invited teen who has lost access can still see the screen, export their data and ask for
    deletion; the endpoints decide which actions each state allows (app/privacy/service.py).
    Once the account is locked for deletion it's refused like everything else (1.2: "can't use
    the app")."""
    if deletion_locked(db, session.user):
        raise AppError(403, "account_being_deleted", BEING_DELETED)
    return session


PrivacySession = Annotated[UserSession, Depends(privacy_session)]
