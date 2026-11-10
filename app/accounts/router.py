from fastapi import APIRouter, Request, Response

from app.accounts import service
from app.accounts.dependencies import ClientSession
from app.accounts.schemas import (
    DeletionNoticeOut,
    EmailChangeRequestBody,
    EmailChangeRequested,
    EntitlementsOut,
    MeOut,
    MyProfileEdit,
    MyProfileOut,
    MyProfileUpdated,
    NextStepOut,
    PolicyAcceptanceRequest,
    PolicyOut,
)
from app.auth import service as auth_service
from app.auth.dependencies import CurrentSession
from app.auth.schemas import ChangePasswordRequest
from app.billing import entitlements
from app.core.database import DbSession
from app.core.email import EmailLater
from app.core.schemas import MessageResponse

router = APIRouter(tags=["account"])


@router.get("/policies/current")
def current_policies(db: DbSession) -> list[PolicyOut]:
    """The policies a new client accepts at sign-up. No sign-in needed."""
    return service.current_policies(db)


@router.get("/me")
def me(session: CurrentSession) -> MeOut:
    return session.user


@router.get("/me/entitlements")
def get_entitlements(session: ClientSession, db: DbSession) -> EntitlementsOut:
    """What the plan allows: the app uses it for the trial banner and the Add Family Member
    upgrade prompt (stories 4.1, 9.1, 10.1)."""
    user = session.user
    return EntitlementsOut(
        plan=entitlements.plan(user),
        trial_ends_at=user.trial_ends_at,
        trial_ended=entitlements.trial_ended(user),
        family_members_included=entitlements.family_members_included(user),
        family_members_used=entitlements.family_members_used(db, user),
    )


@router.get("/me/next-step")
def next_step(session: CurrentSession, db: DbSession) -> NextStepOut:
    """Story 1.2: the first screen to show after sign-in, with the deletion banner during a
    grace period (`deletion_notice`)."""
    step, profile_id = service.next_step(db, session.user)
    notice = service.deletion_notice(db, session.user) if step != "account_being_deleted" else None
    return NextStepOut(
        next_step=step,
        profile_id=profile_id,
        deletion_notice=(
            DeletionNoticeOut(deletion_on=notice[0], banner=notice[1], message=notice[2])
            if notice is not None
            else None
        ),
    )


@router.get("/me/pending-consents")
def pending_consents(session: CurrentSession, db: DbSession) -> list[PolicyOut]:
    """Story 12.2: updated policies the client still has to accept. After revoking consent
    (11.4): the current Terms of Service, Privacy Policy and Health Consent."""
    return service.pending_policies(db, session.user)


@router.post("/me/policy-acceptances")
def accept_policies(
    data: PolicyAcceptanceRequest, session: CurrentSession, request: Request, db: DbSession
) -> MessageResponse:
    """Story 12.2, and giving consent again after revoking it (11.4)."""
    service.accept_pending(db, session.user, data.policy_version_ids, request)
    return MessageResponse(message="Thanks, you’re all set.")


@router.post("/me/password")
def change_password(
    data: ChangePasswordRequest,
    session: CurrentSession,
    request: Request,
    db: DbSession,
    send: EmailLater,
) -> MessageResponse:
    """Story 12.2. Keeps this device signed in and signs out every other device."""
    auth_service.change_password(db, send, session, data, request)
    return MessageResponse(message="Your password has been changed.")


# Story 11.1: Profile & Account


@router.get("/me/profile")
def get_my_profile(session: ClientSession, db: DbSession) -> MyProfileOut:
    """The client's initial, first name, email address, date of birth, country and state, and
    whether an email change is pending. The settings menu is the app's."""
    return service.my_profile(db, session.user)


@router.patch("/me/profile")
def update_my_profile(
    edit: MyProfileEdit, session: ClientSession, request: Request, db: DbSession
) -> MyProfileUpdated:
    """Edit and Save: the first name and the state. A state that would put the client below
    its age of majority answers 409 `teen_rules_confirmation_required` with the story's
    message; send the same edit again with `confirm_teen_rules: true` to save it."""
    return service.update_my_profile(db, session.user, edit, request)


@router.post("/me/email-change-request", status_code=201)
def request_email_change(
    body: EmailChangeRequestBody,
    session: ClientSession,
    request: Request,
    response: Response,
    db: DbSession,
) -> EmailChangeRequested:
    """Request email change: sent to the support team as an Email Change Request. Answers 200
    with the same result when it's a resend."""
    result, created = service.request_email_change(db, session.user, body, request)
    if not created:
        response.status_code = 200
    return result
