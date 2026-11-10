from fastapi import APIRouter, Depends, Request, Response

from app.accounts.dependencies import ClientSession, consented_session
from app.core.database import DbSession
from app.profiles import service
from app.profiles.dependencies import OwnedProfile
from app.profiles.schemas import (
    DeletionRequestBody,
    FamilyMemberResult,
    FamilyOverview,
    IntakeAnswers,
    IntakeCompleted,
    IntakeOut,
    ProfileDetails,
    ProfileEdit,
    ProfileOptions,
    ProfileOut,
    ProfileUpdated,
)

# The policy gate applies to every route here, including ones added later.
router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(consented_session)])


@router.get("")
def list_profiles(session: ClientSession, db: DbSession) -> list[ProfileOut]:
    """Story 4.2's profile panel: the profiles this account can switch to, its own first.
    Turned-off family members are left out; a removed member stays listed, with the status
    "deletion_requested" once the removal's grace period ends, until it's done."""
    return service.list_profiles(db, session.user)


@router.get("/family")
def family_overview(session: ClientSession, db: DbSession) -> FamilyOverview:
    """Story 8.2's Manage Family screen: places in use and a card for each family member."""
    return service.family_overview(db, session.user)


# Declared before /{profile_id}, which would otherwise take "options" as a profile id.
@router.get("/options")
def profile_options() -> ProfileOptions:
    """The answer options for each intake question and View & edit: codes, the stories' labels
    and order, the choice that takes a write-in, and the pronouns selected by default for each
    gender (stories 2.1 and 2.2). They can change without an app release."""
    return service.profile_options()


@router.post("/self", status_code=201)
def start_self_intake(
    session: ClientSession, request: Request, response: Response, db: DbSession
) -> IntakeOut:
    """Story 2.1, step 1 "For myself". Answers 200 with the existing profile if there is one."""
    profile, created = service.start_self_intake(db, session.user, request)
    if not created:
        response.status_code = 200
    return service.intake_out(profile)


@router.post("/family", status_code=201)
def start_family_intake(
    session: ClientSession, request: Request, response: Response, db: DbSession
) -> IntakeOut:
    """Story 2.2: "For a family member" or Add Family Member. Needs room on the client's plan.
    Answers 200 with the unfinished family draft if there is one."""
    profile, created = service.start_family_intake(db, session.user, request)
    if not created:
        response.status_code = 200
    return service.intake_out(profile)


@router.get("/{profile_id}")
def get_profile(profile: OwnedProfile, session: ClientSession) -> ProfileDetails:
    """A profile's details, for View & edit (story 8.2)."""
    return service.profile_details(profile, session.user)


@router.patch("/{profile_id}")
def update_family_member(
    edit: ProfileEdit,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> ProfileUpdated:
    """Story 8.2 View & edit: first name, relationship, gender identity and pronouns."""
    return service.update_family_member(db, profile, edit, session.user, request)


@router.post("/{profile_id}/turn-off")
def turn_off_family_member(
    profile: OwnedProfile, session: ClientSession, request: Request, db: DbSession
) -> FamilyMemberResult:
    """Story 8.2: the member's information is kept and their place is freed. If they were the
    active profile, the app switches to `default_profile_id`."""
    return service.turn_off_family_member(db, profile, session.user, request)


@router.post("/{profile_id}/turn-on")
def turn_on_family_member(
    profile: OwnedProfile, session: ClientSession, request: Request, db: DbSession
) -> FamilyMemberResult:
    """Story 8.2: needs a free place on the plan (403 family_limit_reached otherwise)."""
    return service.turn_on_family_member(db, profile, session.user, request)


@router.post("/{profile_id}/deletion-request")
def request_family_member_deletion(
    body: DeletionRequestBody,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> FamilyMemberResult:
    """Story 8.2 Remove: starts a Family Member Deletion. The member stays fully usable for the
    10-day grace period (the card shows "Scheduled for deletion on [date]"), then is locked
    until the support team deletes them. They keep their place until it's done."""
    return service.request_family_member_deletion(
        db, profile, body.confirm_name, session.user, request
    )


@router.delete("/{profile_id}", status_code=204)
def cancel_intake(
    profile: OwnedProfile, session: ClientSession, request: Request, db: DbSession
) -> Response:
    """Cancels an unfinished intake: no profile is left behind (story 2.2)."""
    service.cancel_intake(db, profile, session.user, request)
    return Response(status_code=204)


@router.get("/{profile_id}/intake")
def get_intake(profile: OwnedProfile) -> IntakeOut:
    """The answers so far and the question to show next."""
    return service.intake_out(profile)


@router.patch("/{profile_id}/intake")
def save_intake(
    answers: IntakeAnswers,
    profile: OwnedProfile,
    session: ClientSession,
    request: Request,
    db: DbSession,
) -> IntakeOut:
    """Saves one step. Earlier steps can be changed until the intake is complete."""
    saved = service.save_intake_answers(db, profile, answers, session.user, request)
    return service.intake_out(saved)


@router.post("/{profile_id}/intake/complete")
def complete_intake(
    profile: OwnedProfile, session: ClientSession, request: Request, db: DbSession
) -> IntakeCompleted:
    return service.complete_intake(db, profile, session.user, request)
