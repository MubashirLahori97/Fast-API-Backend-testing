"""Teens with their own account (stories 1.5, 1.6, 2.4, and the teen parts of 8.2 and 12.2).

- The parent's side takes ClientSession (the policy gate): the invite from the family draft,
  and Manage Family's actions on an invited teen's card. The cards themselves are part of
  GET /profiles/family.
- The teen's setup takes no sign-in: the token in the invite link is the proof, sent in the
  body (it's in the link's `#` fragment, so it never reaches a URL or a log).
- Linking an existing teen account and Create My Account (1.6) take the plain signed-in
  session: a paused or aged-out teen is kept out of everything else by the policy gate.
"""

import uuid

from fastapi import APIRouter, Request

from app.accounts.dependencies import ClientSession
from app.auth.dependencies import CurrentSession
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse
from app.profiles.dependencies import OwnedProfile
from app.teens import service
from app.teens.schemas import (
    AdultAccountBody,
    AdultAccountCreated,
    AdultAccountOut,
    TeenHealthConsentBody,
    TeenInviteBody,
    TeenInviteOut,
    TeenInviteSent,
    TeenInviteToken,
    TeenLinkResult,
    TeenSignedUp,
    TeenSignUpBody,
)

router = APIRouter(tags=["teens"])


# The parent's side (stories 1.5, 2.2, 8.1, 8.2, 12.2)


@router.post("/profiles/{profile_id}/teen-invite", status_code=201)
def invite_teen(
    body: TeenInviteBody,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> TeenInviteSent:
    """Story 1.5 and 2.2's "Teen with their own account", for the family draft whose Teen Profile
    Choice is `own_account` (its `next_question` is `teen_invite`): the parent accepted the Teen
    account privacy disclaimer and typed the teen's email. The invite is emailed and takes a
    family place now; the draft is replaced by the invited teen's card. Needs the Family plan
    (403 `family_plan_required`) and a free place (403 `family_limit_reached`: offer the add-on
    and try again)."""
    return service.start_invite(db, profile, session.user, body, send, request)


@router.post("/teen-links/{link_id}/resend-invite")
def resend_teen_invite(
    link_id: uuid.UUID, session: ClientSession, request: Request, db: DbSession, send: EmailLater
) -> TeenLinkResult:
    """Story 8.2's Resend invite, while the invite is pending: a new link is emailed, and the old
    one stops working."""
    return service.resend_invite(db, link_id, session.user, send, request)


@router.post("/teen-links/{link_id}/turn-off")
def turn_off_teen(
    link_id: uuid.UUID, session: ClientSession, request: Request, db: DbSession
) -> TeenLinkResult:
    """Story 8.2: frees the place; the teen keeps their information but sees only Privacy & Data
    until they're turned back on. Show `turn_off_confirmation` first."""
    return service.turn_off(db, link_id, session.user, request)


@router.post("/teen-links/{link_id}/turn-on")
def turn_on_teen(
    link_id: uuid.UUID, session: ClientSession, request: Request, db: DbSession
) -> TeenLinkResult:
    """Story 8.2: needs a free place (403 `family_limit_reached` otherwise). The teen's access is
    back straight away."""
    return service.turn_on(db, link_id, session.user, request)


@router.post("/teen-links/{link_id}/remove")
def remove_teen(
    link_id: uuid.UUID, session: ClientSession, request: Request, db: DbSession
) -> MessageResponse:
    """Story 8.2's Remove for an invited teen: the place is freed straight away. A teen who
    joined keeps full use for 10 days, then their account is locked and deleted by the team
    (an Invited Teen Removal). Show `remove_confirmation` first."""
    return MessageResponse(message=service.remove(db, link_id, session.user, request))


@router.post("/teen-links/{link_id}/health-consent")
def confirm_teen_health_consent(
    body: TeenHealthConsentBody,
    link_id: uuid.UUID,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> TeenLinkResult:
    """Story 12.2: the parent confirms the updated Health Consent for an invited teen (the card's
    `health_consent_needed`). Until then the teen's access is paused."""
    return service.confirm_health_consent(
        db, link_id, session.user, body.policy_version_id, request
    )


# The teen's side (story 1.5)


@router.post("/teen-invites/check")
def check_teen_invite(body: TeenInviteToken, request: Request, db: DbSession) -> TeenInviteOut:
    """The invite link's setup screen: the email to show locked, and the first name to start
    with. 400 `invite_expired` for an expired, used or made-up link. `account_exists`: open Sign
    In instead."""
    return service.check_invite(db, body.token, request)


@router.post("/teen-invites/accept", status_code=201)
def accept_teen_invite(
    body: TeenSignUpBody, request: Request, db: DbSession, send: EmailLater
) -> TeenSignedUp:
    """Story 1.5's Teen Account Setup. Creates the teen's own account and profile and signs this
    device in (keep `device_token`, as after a code). Then show the welcome, and run the teen
    onboarding (2.3) on `profile_id` with PATCH /profiles/{id}/intake."""
    return service.accept_invite(db, body, send, request)


@router.post("/teen-invites/link")
def link_teen_account(
    body: TeenInviteToken, session: CurrentSession, request: Request, db: DbSession
) -> MessageResponse:
    """Story 1.5's "Teen already has an account": after signing in, a teen account that isn't
    linked to a family joins the invite's. The invite must be for the account's email."""
    return MessageResponse(message=service.link_existing(db, session.user, body.token, request))


# Story 1.6 and 2.4: Create My Account at the age of majority


@router.get("/me/adult-account")
def adult_account(session: CurrentSession, db: DbSession) -> AdultAccountOut:
    """Story 1.6's Create My Account, for a teen account that has reached adult age (next step
    `adult_sign_up`): the adult sign-up with the first name, date of birth and email filled in."""
    return service.adult_account_details(db, session.user)


@router.post("/me/adult-account")
def create_adult_account(
    body: AdultAccountBody, session: CurrentSession, request: Request, db: DbSession
) -> AdultAccountCreated:
    """Stories 1.6 and 2.4: the teen account becomes an adult account in place, with its whole
    history, and the 14-day free trial starts. No onboarding questions again: the app goes to
    `next_step`."""
    return service.create_adult_account(db, session.user, body, request)
