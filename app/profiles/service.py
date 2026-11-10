"""Profiles, the guided health intake and managing family members (stories 2.1, 2.2, 4.2, 8.1,
8.2).

An account's first intake starts at "Who is this profile for?": "For myself" (2.1) or "For a
family member" (2.2). Until one intake is complete, switching that choice discards the other
draft, so at most one unfinished intake exists to resume (story 1.2).

The client's own intake asks sex at birth, gender and pronouns; the date of birth comes from
sign-up. A family member's also asks who they are, their first name and date of birth, the
Teen Profile Choice (13 to 17 only) and the advocate consent.

A finished family member can be edited, turned off and on, or removed (8.2). Removing starts a
deletion request's 10-day grace period with full use (app/privacy/service.py); then the profile
is locked (`deletion_requested_at`) and the support team deletes it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts.models import OPEN_DELETION_STATUSES, DeletionRequest
from app.auth.models import User
from app.auth.schemas import OLDEST_AGE
from app.billing import entitlements
from app.core import audit
from app.core.ages import TEEN_FROM_AGE, age_group, age_on, today, years_before
from app.core.config import settings
from app.core.errors import AppError, database_errors_retryable
from app.profiles import options
from app.profiles.models import Profile
from app.profiles.schemas import (
    CHOOSE_AN_OPTION,
    FAMILY_ONLY_FIELDS,
    FAMILY_QUESTIONS,
    INVALID_DATE_OF_BIRTH,
    SELF_QUESTIONS,
    ChoiceOut,
    FamilyMemberOut,
    FamilyMemberResult,
    FamilyOverview,
    IntakeAnswers,
    IntakeCompleted,
    IntakeOut,
    MemberStatus,
    ProfileDetails,
    ProfileEdit,
    ProfileOptions,
    ProfileOut,
    ProfileUpdated,
    PronounOptionsOut,
    QuestionOptionsOut,
)

# Stories 2.1 and 2.3: any database failure while saving an intake answer.
SAVE_FAILED = "We couldn’t save your answer just now. Please try again."
# Not in the stories (docs/decisions/r2-profiles.md).
OWN_DATE_OF_BIRTH_READ_ONLY = (
    "Your date of birth comes from sign-up, so it can’t be changed here. "
    "If something is wrong, please contact the support team."
)


def _today() -> date:
    """For the ages shown in the profile panel and on Manage Family."""
    return today()


def is_teen(date_of_birth: date | None) -> bool:
    """13 up to the age of majority (story 2.2's age groups): they get the Teen Profile
    Choice. Counted on Hawaii's date, like the age of majority at sign-up (app/core/ages.py)."""
    return date_of_birth is not None and age_group(date_of_birth) == "teen"


def is_under_13(profile: Profile) -> bool:
    """A family member under 13: the gender step shows Girl and Boy (story 2.2). The client's
    own profile never is: account holders are adults (story 1.1)."""
    if profile.is_self or profile.date_of_birth is None:
        return False
    return age_group(profile.date_of_birth) == "under_13"


@contextmanager
def _saving_answer(db: Session) -> Iterator[None]:
    """Like database_errors_retryable, with the intake's own message (stories 2.1 and 2.3). The
    database error's text isn't logged or returned: it can contain the row's values."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", SAVE_FAILED) from None


def first_name(profile: Profile, account: User) -> str:
    return account.first_name if profile.is_self else (profile.first_name or "")


def _questions(profile: Profile) -> tuple[str, ...]:
    return SELF_QUESTIONS if profile.is_self else FAMILY_QUESTIONS


def next_question(profile: Profile) -> str:
    """The first unanswered question, in the stories' order. The Teen Profile Choice is only
    asked for a teen, so it's skipped unless the date of birth makes the member one.

    "teen_invite": the Teen Profile Choice is "own_account", so steps 4 to 7 are skipped and the
    privacy disclaimer and the teen's email come next (stories 2.2 and 1.5), sent to POST
    /profiles/{id}/teen-invite. The draft is replaced by the invite; it's never completed."""
    if profile.intake_completed_at is not None:
        return "done"
    for question in _questions(profile):
        if question == "teen_profile_choice" and not is_teen(profile.date_of_birth):
            continue
        if getattr(profile, question) is None:
            return question
        if question == "teen_profile_choice" and profile.teen_profile_choice == "own_account":
            return "teen_invite"
    return "done"


def _missing_answer_message(profile: Profile, question: str) -> str:
    """Story 2.2's messages for the family steps that need a typed or chosen answer, and the
    stories' "Please choose an option to continue." for the rest. By the date of birth, the
    member's name is known: it's step 2."""
    name = profile.first_name
    if question == "first_name":
        return "What should I call them? Please enter their first name."
    if question == "date_of_birth":
        return f"Please enter a valid date of birth for {name}."
    if question == "teen_profile_choice":
        return f"Please choose how you’d like to set up {name}’s profile."
    if question == "advocate_consent":
        return f"Please let me know how you’re able to look after {name}’s health."
    if question == "teen_invite":
        # Story 1.5: the teen's own account needs the invite, not the remaining steps.
        return "Please enter a valid email address for your teen."
    return CHOOSE_AN_OPTION


def _intake_write_in_message(is_self: bool, name: str | None, field: str) -> str:
    """Stories 2.1 and 2.2. Before a family member's name is known it says "they"/"them"."""
    if field == "gender_identity_other":
        if is_self:
            return "Tell me in your own words how you describe your gender."
        if name:
            return f"Tell me in your own words how {name} describes their gender."
        return "Tell me in your own words how they describe their gender."
    if is_self:
        return "Tell me which pronouns you’d like me to use."
    return f"Tell me which pronouns you’d like me to use for {name or 'them'}."


def _edit_write_in_message(name: str, field: str) -> str:
    """Story 8.2's View & edit wording, which differs from the intake's for gender."""
    if field == "gender_identity_other":
        return f"Tell me in your own words how {name} identifies."
    return f"Tell me which pronouns you’d like me to use for {name}."


def _check_date_of_birth(value: date, name: str | None) -> None:
    """Story 2.2: not in the future. More than 120 years back is a typo, as at sign-up."""
    if value > today() or value < years_before(today(), OLDEST_AGE):
        message = f"Please enter a valid date of birth for {name}." if name else None
        raise AppError(
            422, "invalid_date_of_birth", message or INVALID_DATE_OF_BIRTH, "date_of_birth"
        )


def _check_teen_profile_choice(
    choice: str, date_of_birth: date | None, name: str | None, account: User
) -> None:
    """Only a teen gets the choice. Their own account (an invite, story 1.5) needs the Family
    plan: 1.5's upgrade prompt otherwise. The free place is checked when the invite is sent."""
    if not is_teen(date_of_birth):
        raise AppError(
            422,
            "teen_only",
            f"This question is only for family members aged {TEEN_FROM_AGE} to "
            f"{settings.age_of_majority - 1}.",
            "teen_profile_choice",
        )
    if choice == "own_account":
        from app.teens import service as teens  # app.teens imports this module

        teens.check_can_invite(account, name)


def intake_out(profile: Profile) -> IntakeOut:
    return IntakeOut(
        profile_id=profile.id,
        is_self=profile.is_self,
        family_relationship=profile.family_relationship,
        first_name=None if profile.is_self else profile.first_name,
        date_of_birth=profile.date_of_birth,
        under_13=is_under_13(profile),
        teen_profile_choice=profile.teen_profile_choice,
        advocate_consent=profile.advocate_consent,
        sex_at_birth=profile.sex_at_birth,
        gender_identity=profile.gender_identity,
        gender_identity_other=profile.gender_identity_other,
        pronouns=profile.pronouns,
        pronouns_other=profile.pronouns_other,
        next_question=next_question(profile),
        completed=profile.intake_completed_at is not None,
    )


def _question_fields(question: options.Question) -> dict:
    return {
        "choices": [ChoiceOut(**asdict(choice)) for choice in question.choices],
        "write_in_choice": question.write_in_choice,
        "write_in_field": question.write_in_field,
    }


def profile_options() -> ProfileOptions:
    """The answer options from options.py, for GET /profiles/options."""
    return ProfileOptions(
        family_relationship=QuestionOptionsOut(**_question_fields(options.FAMILY_RELATIONSHIP)),
        teen_profile_choice=QuestionOptionsOut(**_question_fields(options.TEEN_PROFILE_CHOICE)),
        advocate_consent=QuestionOptionsOut(**_question_fields(options.ADVOCATE_CONSENT)),
        sex_at_birth=QuestionOptionsOut(**_question_fields(options.SEX_AT_BIRTH)),
        gender_identity=QuestionOptionsOut(**_question_fields(options.GENDER_IDENTITY)),
        pronouns=PronounOptionsOut(
            **_question_fields(options.PRONOUNS),
            default_for_gender=dict(options.PRONOUNS_DEFAULT_FOR_GENDER),
        ),
    )


def profile_out(profile: Profile, account: User) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        is_self=profile.is_self,
        first_name=first_name(profile, account),
        relationship=profile.family_relationship,
        age=age_on(profile.date_of_birth, _today()) if profile.date_of_birth else None,
        intake_completed=profile.intake_completed_at is not None,
        status=member_status(profile),
    )


def list_profiles(db: Session, account: User) -> list[ProfileOut]:
    """Story 4.2's profile panel: the client's own profile first ("You"), then family members
    in the order they were added. Unfinished family drafts are included, marked
    intake_completed=false. Turned-off members are hidden (story 8.2); a member whose deletion
    was requested stays, with that status, until the deletion is done.

    The first finished profile in the list is the default one (see default_profile)."""
    profiles = db.scalars(
        select(Profile)
        .where(Profile.account_id == account.id, Profile.turned_off_at.is_(None))
        .order_by(Profile.is_self.desc(), Profile.created_at)
    )
    return [profile_out(profile, account) for profile in profiles]


def default_profile(db: Session, account: User) -> Profile | None:
    """Story 4.2: the profile that's active after sign-in, and the one the app switches back to
    when the active family member is turned off or removed (8.2). That's the client's own
    profile, or for advocate-only clients the first active family member."""
    return db.scalars(
        select(Profile)
        .where(
            Profile.account_id == account.id,
            Profile.intake_completed_at.is_not(None),
            Profile.turned_off_at.is_(None),
            Profile.deletion_requested_at.is_(None),
        )
        .order_by(Profile.is_self.desc(), Profile.created_at)
        .limit(1)
    ).first()


def _audit_profile(
    db: Session,
    action: str,
    profile: Profile,
    account: User,
    request: Request,
    details: dict | None = None,
) -> None:
    audit.record(
        db,
        action,
        actor_id=account.id,
        target_type="profile",
        target_id=profile.id,
        request=request,
        details=details,
    )


def _drop_other_first_intake_draft(
    db: Session, account: User, is_self: bool, request: Request
) -> None:
    """Story 2.1 step 1 can be changed with Back. Before any intake is complete, choosing
    "For myself" discards an unfinished family draft, and the other way round."""
    if not needs_intake(db, account):
        return
    # FOR UPDATE waits for a /complete running on the same draft, then re-checks the WHERE,
    # so a draft that was just finished is skipped rather than deleted.
    drafts = db.scalars(
        select(Profile)
        .where(
            Profile.account_id == account.id,
            Profile.is_self.is_(not is_self),
            Profile.intake_completed_at.is_(None),
        )
        .with_for_update()
    ).all()
    for draft in drafts:
        _audit_profile(db, "profile.draft_discarded", draft, account, request)
        db.execute(
            delete(Profile).where(Profile.id == draft.id, Profile.intake_completed_at.is_(None))
        )


def _create_profile(db: Session, account: User, is_self: bool, request: Request) -> Profile:
    # Story 2.1: the client's date of birth was given at sign-up, so it isn't asked again. It's
    # null only on accounts made before sign-up asked for it (dev data).
    profile = Profile(
        account_id=account.id,
        is_self=is_self,
        date_of_birth=account.date_of_birth if is_self else None,
    )
    db.add(profile)
    db.flush()
    _audit_profile(db, "profile.created", profile, account, request, {"is_self": is_self})
    return profile


def _self_profile(db: Session, account: User) -> Profile | None:
    return db.scalar(
        select(Profile).where(Profile.account_id == account.id, Profile.is_self.is_(True))
    )


def start_self_intake(db: Session, account: User, request: Request) -> tuple[Profile, bool]:
    """Story 2.1 step 1, "For myself". Returns (profile, created). Safe to repeat."""
    with _saving_answer(db):
        existing = _self_profile(db, account)
        if existing is not None:
            return existing, False
        _drop_other_first_intake_draft(db, account, is_self=True, request=request)
        try:
            profile = _create_profile(db, account, is_self=True, request=request)
        except IntegrityError:  # two requests at once; the other one created it
            db.rollback()
            return _self_profile(db, account), False
        db.commit()
        return profile, True


def start_family_intake(db: Session, account: User, request: Request) -> tuple[Profile, bool]:
    """Story 2.2: "For a family member", or Add Family Member (8.1). Returns (profile, created).

    The plan must have room (the upgrade or add-on prompt otherwise). An unfinished family
    draft is resumed rather than a second one started."""
    with _saving_answer(db):
        db.refresh(account, with_for_update=True)  # one start at a time per account
        entitlements.check_can_add_family_member(db, account)
        draft = db.scalars(
            select(Profile)
            .where(
                Profile.account_id == account.id,
                Profile.is_self.is_(False),
                Profile.intake_completed_at.is_(None),
            )
            .order_by(Profile.created_at)
            .limit(1)
        ).first()
        if draft is not None:
            db.commit()
            return draft, False
        _drop_other_first_intake_draft(db, account, is_self=False, request=request)
        profile = _create_profile(db, account, is_self=False, request=request)
        db.commit()
        return profile, True


def cancel_intake(db: Session, profile: Profile, account: User, request: Request) -> None:
    """Story 2.2: cancelling leaves no profile behind. Only unfinished intakes can be cancelled;
    removing a finished family profile is story 8.2."""
    db.refresh(profile, with_for_update=True)
    if profile.intake_completed_at is not None:
        raise AppError(
            409,
            "intake_completed",
            "This profile is already set up. You can remove it from Manage Family.",
        )
    _audit_profile(db, "profile.draft_discarded", profile, account, request)
    db.execute(delete(Profile).where(Profile.id == profile.id))
    db.commit()


def save_intake_answers(
    db: Session, profile: Profile, answers: IntakeAnswers, account: User, request: Request
) -> Profile:
    """Saves whichever step was answered, so the client can stop and resume (story 1.2)."""
    with _saving_answer(db):
        db.refresh(profile, with_for_update=True)  # so a parallel /complete can't slip in
        if profile.intake_completed_at is not None:
            raise AppError(
                409,
                "intake_completed",
                "Your intake is already complete. You can update these details in My Health.",
            )
        # Only the fields the client sent, ignoring nulls: a step can be changed, not unanswered.
        sent = answers.model_dump(
            exclude_unset=True, exclude={"gender_identity_other", "pronouns_other"}
        )
        given = {field: value for field, value in sent.items() if value is not None}

        if profile.is_self:
            for field in FAMILY_ONLY_FIELDS:
                if field in given:
                    raise AppError(
                        422, "family_only", "This question is only for family members.", field
                    )
            # The client's own date of birth comes from sign-up (story 2.1). It's accepted
            # unchanged, as View & edit accepts its read-only fields.
            if "date_of_birth" in given:
                if given.pop("date_of_birth") != profile.date_of_birth:
                    raise AppError(422, "read_only", OWN_DATE_OF_BIRTH_READ_ONLY, "date_of_birth")

        name = given.get("first_name", profile.first_name)
        if "date_of_birth" in given:
            _check_date_of_birth(given["date_of_birth"], name)
        date_of_birth = given.get("date_of_birth", profile.date_of_birth)
        if "teen_profile_choice" in given:
            _check_teen_profile_choice(given["teen_profile_choice"], date_of_birth, name, account)

        # A write-in travels with its choice, is required for the choice that takes one ("Not
        # listed" for gender, "Other" for pronouns), and is cleared for any other.
        for choice, question in options.WRITE_IN_QUESTIONS.items():
            if choice in given:
                write_in = question.write_in_field
                value = getattr(answers, write_in)
                if given[choice] == question.write_in_choice and not value:
                    message = _intake_write_in_message(profile.is_self, name, write_in)
                    raise AppError(422, "write_in_required", message, write_in)
                given[write_in] = value

        if given:
            # The consent was given for a particular person. If who they are changes (Back to an
            # earlier step), it no longer applies, and step 4 is asked again.
            identity_changed = any(
                field in given and given[field] != getattr(profile, field)
                for field in ("family_relationship", "first_name", "date_of_birth")
            )
            for field, value in given.items():
                setattr(profile, field, value)
            if not is_teen(profile.date_of_birth) and profile.teen_profile_choice is not None:
                # A new date of birth made them a child or an adult: the choice was for a teen.
                profile.teen_profile_choice = None
            if "advocate_consent" in given:
                # Story 2.2: the consent is recorded with its date and time. Which option was
                # chosen stays on the profile and out of the audit log.
                profile.advocate_consent_at = datetime.now(UTC)
                _audit_profile(db, "profile.advocate_consent_recorded", profile, account, request)
            elif identity_changed and profile.advocate_consent is not None:
                profile.advocate_consent = None
                profile.advocate_consent_at = None
                _audit_profile(db, "profile.advocate_consent_cleared", profile, account, request)
            # Which fields changed, never their values: the audit log holds no health data.
            _audit_profile(
                db, "profile.intake_answered", profile, account, request, {"fields": sorted(given)}
            )
        db.commit()
    return profile


def complete_intake(
    db: Session, profile: Profile, account: User, request: Request
) -> IntakeCompleted:
    with _saving_answer(db):
        db.refresh(profile, with_for_update=True)  # two /complete calls at once audit only once
        missing = next_question(profile)
        if missing != "done":
            message = _missing_answer_message(profile, missing)
            raise AppError(422, "intake_incomplete", message, missing)
        if profile.intake_completed_at is not None:
            # A repeat of the call. The app makes the profile active, so not for one that's off.
            check_can_use(profile)
        else:
            if not profile.is_self:
                # The plan may have changed since the draft was started.
                db.refresh(account, with_for_update=True)
                entitlements.check_can_add_family_member(db, account, profile.first_name)
            profile.intake_completed_at = datetime.now(UTC)
            _audit_profile(db, "profile.intake_completed", profile, account, request)
            # Story 6.1: the health profile's review reminders count from here. Imported here
            # because app.health imports this module.
            from app.health import reminders

            reminders.record_update(db, account, profile)
        db.commit()

    if profile.is_self:
        message = (
            f"Thank you, {account.first_name}. I’m so glad you’re here. "
            "Tell me what’s on your mind, and I’ll ask what I need as we go."
        )
    else:
        message = (
            f"Thank you, {account.first_name}. I’m glad you’re here for {profile.first_name}. "
            "Tell me what’s been going on, and I’ll ask what I need as we go."
        )
    return IntakeCompleted(profile_id=profile.id, message=message)


def needs_intake(db: Session, account: User) -> bool:
    """True until at least one profile on the account has finished its intake (story 1.2)."""
    has_completed = db.scalar(
        select(Profile.id)
        .where(Profile.account_id == account.id, Profile.intake_completed_at.is_not(None))
        .limit(1)
    )
    return has_completed is None


def profile_to_resume(db: Session, account: User) -> Profile | None:
    """The unfinished first intake to return to, or None if step 1 wasn't answered yet."""
    return db.scalars(
        select(Profile)
        .where(Profile.account_id == account.id, Profile.intake_completed_at.is_(None))
        .order_by(Profile.is_self.desc(), Profile.created_at)
        .limit(1)
    ).first()


# Manage Family (story 8.2)


def member_status(profile: Profile, scheduled: bool = False) -> MemberStatus:
    """`scheduled`: removed, and still in the grace period (8.2)."""
    if profile.deletion_requested_at is not None:
        return "deletion_requested"
    if scheduled:
        return "scheduled_for_deletion"
    if profile.turned_off_at is not None:
        return "turned_off"
    return "active"


def open_member_deletion(db: Session, profile: Profile) -> DeletionRequest | None:
    """The member's open deletion request (8.2's Remove), in its grace period or after it."""
    return db.scalar(
        select(DeletionRequest).where(
            DeletionRequest.profile_id == profile.id,
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        )
    )


def family_member_out(profile: Profile, db: Session | None = None) -> FamilyMemberOut:
    """With `db`, the card shows the health profile's completion (story 8.2's "60% complete"),
    and, while a removal's grace period runs, "Scheduled for deletion on [date]"."""
    completion = None
    grace_ends_at = None
    if db is not None:
        from app.accounts import service as accounts  # accounts.service imports this module
        from app.health import service as health  # here, because app.health imports this module

        completion = health.completion(db, profile)
        deletion = open_member_deletion(db, profile)
        if (
            deletion is not None
            and profile.deletion_requested_at is None
            and not accounts.grace_over(deletion)
        ):
            grace_ends_at = deletion.grace_ends_at
    label = None
    if grace_ends_at is not None:
        from app.accounts.service import long_date

        label = f"Scheduled for deletion on {long_date(grace_ends_at)}"
    return FamilyMemberOut(
        id=profile.id,
        first_name=profile.first_name,
        relationship=profile.family_relationship,
        age=age_on(profile.date_of_birth, _today()),
        status=member_status(profile, scheduled=label is not None),
        health_profile_completion=completion,
        deletion_scheduled_on=grace_ends_at,
        deletion_label=label,
    )


def profile_details(profile: Profile, account: User) -> ProfileDetails:
    return ProfileDetails(
        id=profile.id,
        is_self=profile.is_self,
        first_name=first_name(profile, account),
        family_relationship=profile.family_relationship,
        date_of_birth=profile.date_of_birth,
        age=age_on(profile.date_of_birth, _today()) if profile.date_of_birth else None,
        under_13=is_under_13(profile),
        sex_at_birth=profile.sex_at_birth,
        gender_identity=profile.gender_identity,
        gender_identity_other=profile.gender_identity_other,
        pronouns=profile.pronouns,
        pronouns_other=profile.pronouns_other,
        status=member_status(profile),
        intake_completed=profile.intake_completed_at is not None,
    )


def family_overview(db: Session, account: User) -> FamilyOverview:
    """The Manage Family screen: every finished family member, turned off or not, in the order
    they were added, then the invited teens' cards (story 8.2, with no health information), and
    how many of the plan's places are in use, invited teens included (8.1)."""
    from app.teens import service as teens  # app.teens imports this module

    members = db.scalars(
        select(Profile)
        .where(
            Profile.account_id == account.id,
            Profile.is_self.is_(False),
            Profile.intake_completed_at.is_not(None),
        )
        .order_by(Profile.created_at)
    )
    return FamilyOverview(
        family_members_used=entitlements.family_members_used(db, account),
        family_members_included=entitlements.family_members_included(account),
        members=[family_member_out(member, db) for member in members],
        invited_teens=teens.cards(db, account),
    )


def _deletion_requested_error(profile: Profile) -> AppError:
    return AppError(
        409,
        "deletion_requested",
        f"{profile.first_name}’s data is being deleted, so their profile can’t be changed.",
    )


def check_can_use(profile: Profile) -> None:
    """A profile can be used, for conversations and everything after them, once its intake
    is finished (2.1), and while it's on and has no deletion request (8.2).

    The date of birth gives the age group the Oracle follows. Only a client's own profile on an
    account made before sign-up asked for it can be without one (dev data)."""
    if profile.intake_completed_at is None or profile.date_of_birth is None:
        raise AppError(409, "intake_incomplete", "Please finish setting up this profile first.")
    if profile.deletion_requested_at is not None:
        # The client's own profile (an "advocate only" request, 11.4) has no first name of its
        # own, so it gets its own wording (not in the stories; docs/decisions/phase-10-account.md).
        message = (
            "Your data is being deleted, so your profile can’t be used."
            if profile.is_self
            else f"{profile.first_name}’s data is being deleted, so their profile can’t be used."
        )
        raise AppError(409, "deletion_requested", message)
    if profile.turned_off_at is not None:
        raise AppError(409, "profile_turned_off", f"{profile.first_name}’s profile is turned off.")


def _lock_family_member(db: Session, profile: Profile) -> None:
    """Locks the member and checks the 8.2 actions apply to them. The check comes before the
    account lock, so these actions never wait for the account while holding a draft or the
    client's own profile, which the intake endpoints lock in the other order."""
    db.refresh(profile, with_for_update=True)
    _check_family_member(profile)


def _check_family_member(profile: Profile) -> None:
    """A finished family member whose deletion wasn't requested."""
    if profile.is_self:
        raise AppError(409, "not_family_member", "This can only be done for a family member.")
    if profile.intake_completed_at is None:
        raise AppError(409, "intake_incomplete", "Please finish adding this family member first.")
    if profile.deletion_requested_at is not None:
        raise _deletion_requested_error(profile)


def _lock_account(db: Session, account: User) -> None:
    """Taken after the member's lock (the same order as completing an intake). It queues
    turn-ons, turn-offs and removals on one account, so the limit and last-active checks
    count what the others committed: each count is a new statement under READ COMMITTED."""
    db.refresh(account, with_for_update=True)


def _check_someone_else_is_active(db: Session, profile: Profile, account: User) -> None:
    """Story 8.2: an advocate-only client can't turn off or remove their last active family
    member. A client whose own profile is finished always has someone else active. A member
    who was removed doesn't count, in the grace period or after: they'll be gone once it's
    done."""
    being_removed = select(DeletionRequest.profile_id).where(
        DeletionRequest.account_id == account.id,
        DeletionRequest.profile_id.is_not(None),
        DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
    )
    someone_else = db.scalar(
        select(Profile.id)
        .where(
            Profile.account_id == account.id,
            Profile.id != profile.id,
            Profile.intake_completed_at.is_not(None),
            Profile.turned_off_at.is_(None),
            Profile.deletion_requested_at.is_(None),
            Profile.id.not_in(being_removed),
        )
        .limit(1)
    )
    if someone_else is None:
        raise AppError(
            409,
            "last_active_profile",
            f"{profile.first_name} is the only active person on your account. "
            "To remove them, please delete your account instead.",
        )


def _member_result(
    db: Session, profile: Profile, account: User, message: str
) -> FamilyMemberResult:
    default = default_profile(db, account)
    return FamilyMemberResult(
        member=family_member_out(profile, db),
        message=message,
        default_profile_id=default.id if default else None,
    )


def update_family_member(
    db: Session, profile: Profile, edit: ProfileEdit, account: User, request: Request
) -> ProfileUpdated:
    """View & edit: first name, relationship, gender identity and pronouns can change. Date of
    birth and sex at birth decide which questions apply, so they can't (story 8.2, as in 6.1).
    A new relationship needs the advocate consent again (docs/PLAN.md)."""
    with database_errors_retryable(db):
        _lock_family_member(db, profile)
        if "first_name" in edit.model_fields_set and edit.first_name is None:
            raise AppError(
                422, "first_name_required", "Please enter their first name.", "first_name"
            )
        name = edit.first_name or profile.first_name

        for field in ("date_of_birth", "sex_at_birth"):
            value = getattr(edit, field)
            if value is not None and value != getattr(profile, field):
                raise AppError(
                    422,
                    "read_only",
                    f"{name}’s date of birth and sex assigned at birth can’t be changed here. "
                    "If something is wrong, please contact the support team.",
                    field,
                )

        sent = edit.model_dump(
            exclude_unset=True,
            exclude={
                "advocate_consent",
                "gender_identity_other",
                "pronouns_other",
                "date_of_birth",
                "sex_at_birth",
            },
        )
        given = {field: value for field, value in sent.items() if value is not None}
        changed = {f: value for f, value in given.items() if getattr(profile, f) != value}

        # A write-in goes with the sent choice, or the saved one if only the write-in was sent.
        # It's required for the choice that takes one and cleared for any other.
        for choice, question in options.WRITE_IN_QUESTIONS.items():
            write_in = question.write_in_field
            if choice not in given and write_in not in edit.model_fields_set:
                continue
            chosen = given.get(choice, getattr(profile, choice))
            if write_in in edit.model_fields_set:
                value = getattr(edit, write_in)
            else:
                value = getattr(profile, write_in)
            if chosen != question.write_in_choice:
                value = None
            elif not value:
                message = _edit_write_in_message(name, write_in)
                raise AppError(422, "write_in_required", message, write_in)
            if value != getattr(profile, write_in):
                changed[write_in] = value

        consent_given = edit.advocate_consent is not None
        if "family_relationship" in changed and not consent_given:
            raise AppError(
                422,
                "consent_required",
                f"Please let me know how you’re able to look after {name}’s health.",
                "advocate_consent",
            )
        if consent_given and (
            "family_relationship" in changed or edit.advocate_consent != profile.advocate_consent
        ):
            changed["advocate_consent"] = edit.advocate_consent

        if changed:
            for field, value in changed.items():
                setattr(profile, field, value)
            if "advocate_consent" in changed:
                profile.advocate_consent_at = datetime.now(UTC)
                _audit_profile(db, "profile.advocate_consent_recorded", profile, account, request)
            # Which fields changed, never their values. A write-in is listed as its choice, so
            # the log doesn't show that someone described their own gender or pronouns.
            fields = sorted({field.removesuffix("_other") for field in changed})
            _audit_profile(db, "profile.updated", profile, account, request, {"fields": fields})
        db.commit()
    return ProfileUpdated(
        profile=profile_details(profile, account),
        message=f"Thanks, I’ve updated {profile.first_name}’s details.",
    )


def turn_off_family_member(
    db: Session, profile: Profile, account: User, request: Request
) -> FamilyMemberResult:
    """Their information is kept; they're hidden from the profile panel, can't be used, and
    free their place. Turning off a member who's already off changes nothing."""
    with database_errors_retryable(db):
        _lock_family_member(db, profile)
        _lock_account(db, account)
        if profile.turned_off_at is None:
            _check_someone_else_is_active(db, profile, account)
            profile.turned_off_at = datetime.now(UTC)
            _audit_profile(db, "profile.turned_off", profile, account, request)
            db.commit()
        return _member_result(
            db, profile, account, f"{profile.first_name}’s profile is turned off."
        )


def turn_on_family_member(
    db: Session, profile: Profile, account: User, request: Request
) -> FamilyMemberResult:
    """Needs a free place on the plan (the upgrade or add-on prompt otherwise). Turning on a
    member who's already on changes nothing."""
    with database_errors_retryable(db):
        _lock_family_member(db, profile)
        _lock_account(db, account)
        if profile.turned_off_at is not None:
            entitlements.check_can_turn_on_family_member(db, account, profile.first_name)
            profile.turned_off_at = None
            _audit_profile(db, "profile.turned_on", profile, account, request)
            db.commit()
        return _member_result(db, profile, account, f"{profile.first_name}’s profile is turned on.")


def request_family_member_deletion(
    db: Session, profile: Profile, confirm_name: str | None, account: User, request: Request
) -> FamilyMemberResult:
    """Remove (8.2, 6 Nov 19:22): the client types the member's first name, and a Family Member
    Deletion starts. The client is acknowledged straight away. For the 10-day grace period the
    profile stays fully usable (the client can keep using it and download the member's
    information) and its card shows "Scheduled for deletion on [date]"; it keeps its place.
    Then the profile is locked and the request goes to the support team (app/privacy/service.py),
    who delete it within 45 calendar days. Asking again for the same member changes nothing."""
    from app.accounts.service import long_date  # accounts.service imports this module
    from app.notifications import service as notifications
    from app.privacy import service as privacy

    def received(deletion: DeletionRequest) -> str:
        return (
            f"Your request has been received. {name}’s profile will be deleted after "
            f"{long_date(deletion.grace_ends_at)}. You can keep using it until then."
        )

    with database_errors_retryable(db):
        db.refresh(profile, with_for_update=True)
        name = profile.first_name
        if not profile.is_self:
            existing = open_member_deletion(db, profile)
            if existing is not None and existing.grace_ends_at is not None:
                return _member_result(db, profile, account, received(existing))
        _check_family_member(profile)
        if (confirm_name or "").strip().casefold() != name.casefold():
            raise AppError(
                422,
                "name_mismatch",
                f"Please type {name}’s first name to confirm.",
                "confirm_name",
            )
        _lock_account(db, account)
        if profile.turned_off_at is None:
            _check_someone_else_is_active(db, profile, account)

        deletion = privacy.start_request(
            db,
            account_id=account.id,
            kind="family_member",
            actor_id=account.id,
            request=request,
            profile_id=profile.id,
        )
        _audit_profile(
            db,
            "profile.deletion_requested",
            profile,
            account,
            request,
            {"deletion_request_id": str(deletion.id)},
        )
        # The acknowledgement (8.2, Super Admin 5.2), with its email copy.
        notifications.notify(
            db,
            account,
            "member_deletion_acknowledged",
            profile=profile,
            data={"date": long_date(deletion.grace_ends_at)},
        )
        audit.record(
            db,
            "deletion.acknowledged",
            actor_id=account.id,
            target_type="deletion_request",
            target_id=deletion.id,
            request=request,
            details={"kind": deletion.kind},
        )
        message = received(deletion)
        db.commit()
        return _member_result(db, profile, account, message)
