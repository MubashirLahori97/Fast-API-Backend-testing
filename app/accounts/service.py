"""The account: policy acceptance (stories 1.1 and 12.2), where the app goes after sign-in
(story 1.2), whether consent is withdrawn (story 11.4), and Profile & Account (story 11.1).

Revoking consent, exports and deletion requests are in app/privacy/; this module holds the
state the policy gate reads, so the gate and the other packages don't depend on app/privacy.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import Request
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts import emails
from app.accounts.models import (
    ACCOUNT_DELETION_KINDS,
    OPEN_DELETION_STATUSES,
    ConsentRevocation,
    DeletionRequest,
    PolicyAcceptance,
    PolicyVersion,
)
from app.accounts.schemas import (
    INVALID_ZIP_CODE,
    EmailChangeRequestBody,
    EmailChangeRequested,
    MyProfileEdit,
    MyProfileOut,
    MyProfileUpdated,
)
from app.auth.models import (
    PasswordResetToken,
    TrustedDevice,
    User,
    UserSession,
    VerificationChallenge,
)
from app.billing import entitlements
from app.conversations.models import HealthConsent
from app.core import audit, jobs
from app.core.ages import HAWAII, age_on, us_today
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import AppError, database_errors_retryable
from app.core.zip_codes import zip_in_state
from app.notifications import service as notifications
from app.privacy import teens
from app.profiles import service as profiles
from app.profiles.models import Profile
from app.support import service as support
from app.support.models import SupportRequest

# Policies every account accepts. The Health Consent is accepted per profile (story 3.1).
ACCOUNT_POLICY_KINDS = ("terms", "privacy")
# Story 11.4: after revoking consent, the client accepts all three again.
RECONSENT_POLICY_KINDS = ("terms", "privacy", "health_consent")

# Story 11.4's messages.
CONSENT_NEEDED = (
    "Please accept our Terms of Service, Privacy Policy and Health Consent to continue."
)
ALREADY_SCHEDULED = "Your account is already scheduled for deletion."
# Stories 1.2 and 11.4: after the grace period, the account (and its invited teens' accounts)
# is locked.
BEING_DELETED = "Your account is being deleted, so it’s no longer available."
SAVE_ACCEPTANCE_FAILED = "We couldn’t save your acceptance just now. Please try again."


def _now() -> datetime:
    return datetime.now(UTC)


def current_policies(
    db: Session, kinds: tuple[str, ...] = ACCOUNT_POLICY_KINDS
) -> list[PolicyVersion]:
    """The latest published version of each policy kind asked for (the account policies by
    default)."""
    stmt = (
        select(PolicyVersion)
        .where(PolicyVersion.kind.in_(kinds), PolicyVersion.published_at <= _now())
        .order_by(PolicyVersion.kind, PolicyVersion.published_at.desc())
        .ext(distinct_on(PolicyVersion.kind))
    )
    return list(db.scalars(stmt))


def _accepted_ids(db: Session, user: User) -> set[uuid.UUID]:
    stmt = select(PolicyAcceptance.policy_version_id).where(PolicyAcceptance.user_id == user.id)
    return set(db.scalars(stmt))


# Story 11.4: consent and whole-account deletion, which the policy gate reads


def _open_revocation(db: Session, user: User, *, lock: bool = False) -> ConsentRevocation | None:
    stmt = select(ConsentRevocation).where(
        ConsentRevocation.account_id == user.id, ConsentRevocation.restored_at.is_(None)
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def consent_revoked(db: Session, user: User) -> bool:
    """The client revoked their consent and hasn't given it again (story 11.4)."""
    return _open_revocation(db, user) is not None


def open_account_deletion(db: Session, user: User) -> DeletionRequest | None:
    """A request to delete the whole account (an Account Deletion, an invited teen's removal, or
    a teen's own) that hasn't been carried out or declined, in its grace period or after it."""
    return db.scalar(
        select(DeletionRequest).where(
            DeletionRequest.account_id == user.id,
            DeletionRequest.profile_id.is_(None),
            DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        )
    )


def _unfinished_account_deletion(db: Session, account_id: uuid.UUID) -> DeletionRequest | None:
    """An open whole-account request, or a completed one the purge hasn't carried out yet."""
    return db.scalar(
        select(DeletionRequest)
        .where(
            DeletionRequest.account_id == account_id,
            DeletionRequest.kind.in_(ACCOUNT_DELETION_KINDS),
            or_(
                DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
                and_(DeletionRequest.status == "completed", DeletionRequest.purged_at.is_(None)),
            ),
        )
        .order_by(DeletionRequest.requested_at)
        .limit(1)
    )


def grace_over(deletion: DeletionRequest, now: datetime | None = None) -> bool:
    """Past the grace period: the account or profile is locked. The privacy sweep sets
    `locked_at` when it ends; a grace period whose end has passed counts as over before the
    sweep gets to it, so the lock starts on time. A legal hold placed during the grace period
    doesn't end it early. A teen's request by email has none."""
    if deletion.locked_at is not None or deletion.grace_ends_at is None:
        return True
    return deletion.grace_ends_at <= (now or _now())


@dataclass(frozen=True)
class AccountDeletion:
    """Where an account stands with a deletion (stories 1.2 and 11.4)."""

    request: DeletionRequest
    # Past the grace period: "Your account is being deleted, so it’s no longer available."
    locked: bool
    # An invited teen on a parent's account that's being deleted (11.4).
    via_parent: bool

    @property
    def deletion_on(self) -> datetime | None:
        """The end of the grace period: the [date] the messages show."""
        return self.request.grace_ends_at


def account_deletion(db: Session, user: User) -> AccountDeletion | None:
    """The account's own deletion request, or, for an invited teen, the deletion of the parent's
    account, which deletes the teen's account too (11.4). A locked one wins over one still in
    its grace period, and the account's own request over the parent's."""
    found: list[AccountDeletion] = []
    own = _unfinished_account_deletion(db, user.id)
    if own is not None:
        found.append(AccountDeletion(own, grace_over(own), via_parent=False))
    if user.account_type == "teen":
        parent_id = teens.parent_account_id(db, user)
        parent = _unfinished_account_deletion(db, parent_id) if parent_id else None
        if parent is not None and parent.kind == "account":
            found.append(AccountDeletion(parent, grace_over(parent), via_parent=True))
    if not found:
        return None
    return next((item for item in found if item.locked), found[0])


def deletion_locked(db: Session, user: User) -> bool:
    """Past the grace period: only sign-in, /me, /me/next-step and sign-out still answer, and
    the app shows BEING_DELETED (stories 1.2 and 11.4)."""
    state = account_deletion(db, user)
    return state is not None and state.locked


def long_date(moment: datetime) -> str:
    """ "December 5, 2026", on the date in Hawaii, like billing's dates: the last US state to
    reach each date, so a day we promise use until has come everywhere the client could be."""
    day = moment.astimezone(HAWAII).date()
    return f"{day:%B} {day.day}, {day.year}"


def scheduled_banner(moment: datetime) -> str:
    """Stories 1.2 and 11.4's grace period banner, on every screen."""
    return f"Your account is scheduled for deletion on {long_date(moment)}."


def teen_deletion_message(state: AccountDeletion) -> str | None:
    """Story 11.4's message shown to an invited teen whose parent asked to delete their
    account, and 8.2's to a teen the parent removed; None for the account's own request."""
    if state.deletion_on is None:
        return None
    until = long_date(state.deletion_on)
    if state.via_parent:
        return (
            "Your parent or guardian has asked to delete their account. You can keep using Your "
            f"Oracle and download your information until {until}. After that, your account and "
            "information will be deleted."
        )
    if state.request.kind == "teen_removal":
        return (
            "Your parent or guardian has removed you from their family plan. You can keep using "
            f"Your Oracle and download your information until {until}. After that, your account "
            "and information will be deleted."
        )
    return None


def deletion_notice(db: Session, user: User) -> tuple[datetime, str, str | None] | None:
    """During a grace period: the deletion date, the banner, and the teen's message when the
    deletion is the parent's doing (stories 1.2, 8.2 and 11.4). None otherwise, and once the
    account is locked."""
    state = account_deletion(db, user)
    if state is None or state.locked or state.deletion_on is None:
        return None
    return state.deletion_on, scheduled_banner(state.deletion_on), teen_deletion_message(state)


def consent_withdrawn(db: Session, user: User) -> bool:
    """Story 11.4: the Oracle, analytics and notifications mustn't use this account's
    information. True while consent is revoked, and once the account is locked for deletion
    (after the grace period; during it, everything is used as normal).
    notifications.service.consent_revoked applies the same rule.

    A teen with their own account has no consent of their own: the parent's counts for them
    (1.5). So it's also withdrawn while the parent's is, and when no parent is linked any more
    (removed, or the parent's account deleted), except during a removal's grace period (8.2:
    the teen keeps full use)."""
    if consent_revoked(db, user) or deletion_locked(db, user):
        return True
    return support.is_teen_account(user) and teens.parent_consent_withdrawn(db, user)


def pending_policies(db: Session, user: User) -> list[PolicyVersion]:
    """Current policy versions the user hasn't accepted yet. After revoking consent, that's the
    current Terms of Service, Privacy Policy and Health Consent, whatever was accepted before
    (story 11.4: "they're shown the Terms of Service, Privacy Policy and Health Consent").

    None for a teen with their own account: the parent gave consent for them, so they're never
    shown the policy screen (1.5, 12.2). Until the parent accepts an update, the teen is paused
    instead (app/teens/access.py)."""
    if support.is_teen_account(user):
        return []
    if consent_revoked(db, user):
        return current_policies(db, RECONSENT_POLICY_KINDS)
    accepted = _accepted_ids(db, user)
    return [policy for policy in current_policies(db) if policy.id not in accepted]


def record_acceptances(
    db: Session, user: User, policies: list[PolicyVersion], request: Request | None = None
) -> None:
    """Records acceptance of each policy (skipping ones already accepted). Caller commits."""
    accepted = _accepted_ids(db, user)
    for policy in policies:
        if policy.id in accepted:
            continue
        db.add(PolicyAcceptance(user_id=user.id, policy_version_id=policy.id))
        audit.record(
            db,
            "policy.accepted",
            actor_id=user.id,
            target_type="policy_version",
            target_id=policy.id,
            request=request,
            details={"kind": policy.kind, "version": policy.version},
        )


def accept_pending(
    db: Session, user: User, accepted_ids: list[uuid.UUID], request: Request
) -> None:
    """Story 12.2: every updated policy must be accepted before the client continues. After
    revoking consent, accepting the three policies gives consent again (story 11.4)."""
    if consent_revoked(db, user):
        _give_consent_again(db, user, accepted_ids, request)
        return
    pending = pending_policies(db, user)
    missing = [policy for policy in pending if policy.id not in set(accepted_ids)]
    if missing:
        # One message per unticked policy, so the app can show each under its own checkbox.
        details = [
            {
                "field": "policy_version_ids",
                "policy_version_id": str(policy.id),
                "message": (
                    f"Please confirm you’ve read and accept the updated {policy.title} to continue."
                ),
            }
            for policy in missing
        ]
        raise AppError(
            422,
            "policy_not_accepted",
            details[0]["message"],
            "policy_version_ids",
            details=details,
        )
    record_acceptances(db, user, pending, request)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", SAVE_ACCEPTANCE_FAILED) from None


def _accept_own_health_consent(
    db: Session, user: User, policy: PolicyVersion, request: Request
) -> None:
    """Records the Health Consent for the client's own profile, if they have one and haven't
    accepted this version for it. Family members' consents are kept as they were: the client
    continues "as before" (story 11.4)."""
    own = db.scalar(select(Profile).where(Profile.account_id == user.id, Profile.is_self))
    if own is None:
        return
    accepted = db.scalar(
        select(HealthConsent.id).where(
            HealthConsent.profile_id == own.id,
            HealthConsent.policy_version_id == policy.id,
            HealthConsent.accepted_by_id == user.id,
        )
    )
    if accepted is not None:
        return
    db.add(HealthConsent(profile_id=own.id, policy_version_id=policy.id, accepted_by_id=user.id))
    audit.record(
        db,
        "health_consent.accepted",
        actor_id=user.id,
        target_type="profile",
        target_id=own.id,
        request=request,
        details={"version": policy.version},
    )


def _give_consent_again(
    db: Session, user: User, accepted_ids: list[uuid.UUID], request: Request
) -> None:
    """Story 11.4: the client signs in after revoking consent and accepts the Terms of Service,
    Privacy Policy and Health Consent. They continue as before, with all their data, and their
    invited teens' access comes back. Refused once the account is locked for deletion; allowed
    during the grace period, when everything works as normal."""
    policies = current_policies(db, RECONSENT_POLICY_KINDS)
    if any(policy.id not in set(accepted_ids) for policy in policies):
        raise AppError(422, "consent_required", CONSENT_NEEDED, "policy_version_ids")
    try:
        db.refresh(user, with_for_update=True)
        if deletion_locked(db, user):
            db.rollback()
            raise AppError(403, "account_being_deleted", BEING_DELETED)
        revocation = _open_revocation(db, user, lock=True)
        if revocation is None:  # given again on another device meanwhile
            db.rollback()
            return
        record_acceptances(
            db, user, [p for p in policies if p.kind in ACCOUNT_POLICY_KINDS], request
        )
        for policy in policies:
            if policy.kind == "health_consent":
                _accept_own_health_consent(db, user, policy, request)
        revocation.restored_at = _now()
        audit.record(
            db,
            "consent.given_again",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            request=request,
        )
        teens.restore_after_consent(db, user)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", SAVE_ACCEPTANCE_FAILED) from None


def next_step(db: Session, user: User) -> tuple[str, uuid.UUID | None]:
    """The first screen that applies after sign-in, in the order story 1.2 gives, plus a
    profile: for "intake" the one to resume (None when no intake was started), and for
    "dashboard" the one to make active (story 4.2). Before all of them, an account locked for
    deletion after its grace period gets "account_being_deleted" (1.2); during the grace period
    the client signs in as normal (deletion_notice gives the banner). A teen who has lost access
    only gets Privacy & Data (story 11.4), and a teen
    account that has reached the age of majority gets Create My Account (1.6). A teen with
    access goes to the teen onboarding (2.3) and then "dashboard", which the app opens as the
    teen's own chat (3.1)."""
    if deletion_locked(db, user):
        return "account_being_deleted", None
    if teens.age_of_majority_reached(db, user):
        return "adult_sign_up", None
    if teens.access_paused(db, user):
        return "access_paused", None
    if pending_policies(db, user):
        return "policy_update", None
    if profiles.needs_intake(db, user):
        resume = profiles.profile_to_resume(db, user)
        return "intake", resume.id if resume else None
    if entitlements.trial_ended(user):
        return "upgrade", None
    default = profiles.default_profile(db, user)
    return "dashboard", default.id if default else None


def sign_out_everywhere(db: Session, user: User, *, forget_devices: bool) -> int:
    """Ends every signed-in session of the account, with the general "signed out" message, and
    returns how many ended. With `forget_devices`, trusted devices are cleared too (so the next
    sign-in needs two-step verification) and open codes and reset links close. The caller
    commits. Push devices stop getting pushes until the app signs in again."""
    now = _now()
    ended = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if forget_devices:
        db.execute(delete(TrustedDevice).where(TrustedDevice.user_id == user.id))
        db.execute(
            update(VerificationChallenge)
            .where(
                VerificationChallenge.user_id == user.id, VerificationChallenge.used_at.is_(None)
            )
            .values(used_at=now)
        )
        db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
    return ended


# Story 11.1: Profile & Account

# The 50 states and Washington, D.C., for "In [State], the age of majority is...".
STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "Washington, D.C.",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

# Not in the stories (docs/decisions/phase-10-account.md).
DETAILS_UPDATED = "Your details have been updated."
EMAIL_READ_ONLY = (
    "Your email address is used to sign in, so it can’t be changed here. "
    "Please use Request email change."
)
SAME_EMAIL = "This is already your email address."
EMAIL_IN_USE = "This email address is already used by another account."
EMAIL_CHANGE_PENDING = (
    "You’ve already asked to change your email address. The support team will be in touch."
)
EMAIL_CHANGED = "The email address has been changed, and the client has been told."
EMAIL_CHANGE_DONE = "This email change request has already been resolved."
# Story 11.1: what the profile shows until the team makes the change.
EMAIL_CHANGE_REQUESTED = "Email change requested"


def age_of_majority_in(state: str | None) -> int:
    """Story 11.1: the state decides the age of majority used for age rules. It's 18 in every
    state (docs/PLAN.md, question 22), so every state gives `settings.age_of_majority`. A
    per-state table (19 in Alabama and Nebraska, 21 in Mississippi) would go in
    app/core/ages.py, used here and by is_adult and age_group alike."""
    return settings.age_of_majority


def adult_in(date_of_birth: date, state: str | None) -> bool:
    """At or over the state's age of majority, counted on Hawaii's date like is_adult."""
    return age_on(date_of_birth, us_today()) >= age_of_majority_in(state)


def age_rules(account: User) -> Literal["adult", "teen"]:
    if account.date_of_birth is None or adult_in(account.date_of_birth, account.state):
        return "adult"
    return "teen"


def teen_rules_message(state: str) -> str:
    """Story 11.1: shown before saving a state that would put the client below its age of
    majority. They choose Confirm (sent again with confirm_teen_rules) or Cancel."""
    age = age_of_majority_in(state)
    return (
        f"In {STATE_NAMES.get(state, state)}, the age of majority is {age}. If you change your "
        f"state, teen rules will apply until you turn {age}. This means I’ll share health "
        "education only, without product recommendations. Do you want to continue?"
    )


def _advocate_only(db: Session, account: User) -> bool:
    """Story 11.1: an account that's past onboarding with no health profile of its own in use:
    they deleted their own data (11.4's advocate only) or only ever added family members."""
    if profiles.needs_intake(db, account):
        return False
    own = db.scalar(
        select(Profile.id).where(
            Profile.account_id == account.id,
            Profile.is_self,
            Profile.intake_completed_at.is_not(None),
            Profile.deletion_requested_at.is_(None),
        )
    )
    return own is None


def my_profile(db: Session, account: User) -> MyProfileOut:
    """The Profile & Account screen's details (story 11.1)."""
    pending = support.open_email_change(db, account)
    return MyProfileOut(
        first_name=account.first_name,
        initial=account.first_name[:1].upper(),
        email=account.email,
        date_of_birth=account.date_of_birth,
        country=account.country,
        state=account.state,
        state_name=STATE_NAMES.get(account.state) if account.state else None,
        zip_code=account.zip_code,
        age_rules=age_rules(account),
        email_change_requested=pending is not None,
        requested_email=pending.requested_email if pending is not None else None,
        advocate_only=_advocate_only(db, account),
    )


def _audit_account(
    db: Session, action: str, account: User, request: Request | None, details: dict | None = None
) -> None:
    audit.record(
        db,
        action,
        actor_id=account.id,
        target_type="user",
        target_id=account.id,
        request=request,
        details=details,
    )


def update_my_profile(
    db: Session, account: User, edit: MyProfileEdit, request: Request
) -> MyProfileUpdated:
    """Edit and Save (story 11.1): the first name, the state and the ZIP code (the ZIP code
    doesn't change the age rules; only the state does). A new state is checked
    against the client's date of birth: if it would put them below its age of majority, the
    story's message comes back first (409), and the change is saved only once they confirm.
    Every change is audited, and a state change or a change of age rules separately, with the
    old and new state (no other values)."""
    with database_errors_retryable(db):
        db.refresh(account, with_for_update=True)
        sent = edit.model_fields_set
        if "first_name" in sent and edit.first_name is None:
            raise AppError(
                422, "first_name_required", "Please enter your first name.", "first_name"
            )
        if "state" in sent and edit.state is None:
            raise AppError(422, "state_required", "Please choose your state.", "state")
        if "zip_code" in sent and edit.zip_code is None:
            raise AppError(422, "zip_code_required", INVALID_ZIP_CODE, "zip_code")
        if edit.email is not None and edit.email != account.email:
            raise AppError(422, "read_only", EMAIL_READ_ONLY, "email")
        if edit.date_of_birth is not None and edit.date_of_birth != account.date_of_birth:
            raise AppError(422, "read_only", profiles.OWN_DATE_OF_BIRTH_READ_ONLY, "date_of_birth")

        changed: dict[str, str] = {}
        if edit.first_name is not None and edit.first_name != account.first_name:
            changed["first_name"] = edit.first_name
        if edit.zip_code is not None and edit.zip_code != account.zip_code:
            changed["zip_code"] = edit.zip_code
        old_state = account.state
        new_state = edit.state if edit.state is not None else old_state
        # The ZIP code must belong to the state the client will have after saving (1.1, 11.1).
        # A new ZIP code is checked against it, and so is the one on file when only the state
        # changes, so the app then asks for the new state's ZIP code too.
        new_zip = edit.zip_code if edit.zip_code is not None else account.zip_code
        zip_or_state_changed = "zip_code" in changed or new_state != old_state
        if new_zip and new_state and zip_or_state_changed and not zip_in_state(new_zip, new_state):
            db.rollback()
            raise AppError(422, "zip_code_not_in_state", INVALID_ZIP_CODE, "zip_code")
        rules_change: str | None = None
        if new_state != old_state:
            changed["state"] = new_state
            dob = account.date_of_birth
            if dob is not None:
                was_adult = adult_in(dob, old_state)
                will_be_adult = adult_in(dob, new_state)
                if was_adult and not will_be_adult and not edit.confirm_teen_rules:
                    db.rollback()
                    raise AppError(
                        409,
                        "teen_rules_confirmation_required",
                        teen_rules_message(new_state),
                        "state",
                    )
                if was_adult != will_be_adult:
                    rules_change = "adult" if will_be_adult else "teen"

        if changed:
            for field, value in changed.items():
                setattr(account, field, value)
            _audit_account(
                db, "account.details_updated", account, request, {"fields": sorted(changed)}
            )
            if "state" in changed:
                _audit_account(
                    db,
                    "account.state_changed",
                    account,
                    request,
                    {"from": old_state, "to": new_state},
                )
            if rules_change is not None:
                # 11.1: "any change of age rules is recorded in the backend logs".
                _audit_account(
                    db, "account.age_rules_changed", account, request, {"to": rules_change}
                )
        db.commit()
    return MyProfileUpdated(profile=my_profile(db, account), message=DETAILS_UPDATED)


def request_email_change(
    db: Session, account: User, body: EmailChangeRequestBody, request: Request
) -> tuple[EmailChangeRequested, bool]:
    """Story 11.1's Request email change: an Email Change Request for the support team, who
    change the address in the admin panel (`change_email`). Until then the client keeps signing
    in with their current address. Returns (result, created); safe to repeat with the same
    client_request_id."""
    with database_errors_retryable(db):
        # One at a time per account, so "already pending" and the hourly limit hold.
        db.refresh(account, with_for_update=True)
        resent = db.scalar(
            select(SupportRequest.id).where(
                SupportRequest.account_id == account.id,
                SupportRequest.client_request_id == body.client_request_id,
                SupportRequest.kind == "email_change",
            )
        )
        if resent is not None:
            db.rollback()
            result = EmailChangeRequested(
                profile=my_profile(db, account), message=EMAIL_CHANGE_REQUESTED
            )
            return result, False
        if body.new_email == account.email:
            raise AppError(422, "same_email", SAME_EMAIL, "new_email")
        if support.open_email_change(db, account) is not None:
            raise AppError(409, "email_change_pending", EMAIL_CHANGE_PENDING, "new_email")
        taken = db.scalar(select(User.id).where(User.email == body.new_email))
        if taken is not None:
            raise AppError(409, "email_taken", EMAIL_IN_USE, "new_email")
        support.add_email_change(db, account, body.new_email, body.client_request_id, request)
        db.commit()
    result = EmailChangeRequested(profile=my_profile(db, account), message=EMAIL_CHANGE_REQUESTED)
    return result, True


def change_email(
    db: Session,
    admin: User,
    support_request_id: uuid.UUID,
    send: SendEmail,
    request: Request | None = None,
) -> str:
    """The support team's Change email address on an Email Change Request (Super Admin 5.1 and
    3.1), for Phase A's admin endpoint. Story 11.1, once it's changed:

    - the client is told at both addresses (the in-app notice's email copy goes to the new one);
    - every session ends and trusted devices are cleared, so the next sign-in, with the new
      address, needs two-step verification; open codes and reset links close too;
    - the request is resolved automatically, and the change is audited with who made it.

    An address that another account took meanwhile isn't changed (409); the team contacts the
    client (Super Admin 5.1's alternate scenario)."""
    if admin.role not in support.TEAM_ROLES:
        raise AppError(403, "not_allowed", support.NOT_ALLOWED)
    with database_errors_retryable(db):
        support_request = db.get(SupportRequest, support_request_id, with_for_update=True)
        if support_request is None or support_request.kind != "email_change":
            raise AppError(404, "support_request_not_found", support.REQUEST_NOT_FOUND)
        if support_request.status != "open":
            raise AppError(409, "already_resolved", EMAIL_CHANGE_DONE)
        account = db.get(User, support_request.account_id, with_for_update=True)
        new_email = support_request.requested_email
        taken = db.scalar(select(User.id).where(User.email == new_email, User.id != account.id))
        if taken is not None:
            db.rollback()
            raise AppError(409, "email_taken", EMAIL_IN_USE)
        old_email = account.email
        account.email = new_email
        try:
            db.flush()
        except IntegrityError:  # an account with this address was created meanwhile
            db.rollback()
            raise AppError(409, "email_taken", EMAIL_IN_USE) from None
        sign_out_everywhere(db, account, forget_devices=True)
        support.mark_email_change_done(db, admin, support_request, request)
        audit.record(
            db,
            "account.email_changed",
            actor_id=admin.id,
            target_type="user",
            target_id=account.id,
            request=request,
            details={"support_request_id": str(support_request.id)},
        )
        noticed = notifications.notify(db, account, "email_changed", data={"new_email": new_email})
        db.commit()
    send(emails.email_changed_old_address(old_email))
    if noticed is None:
        send(emails.email_changed_new_address(new_email))
    return EMAIL_CHANGED


# Story 12.2: publishing a new version. Phase A's admin panel calls this; there's no endpoint yet.

POLICY_KINDS = ("terms", "privacy", "health_consent")
# Not in the stories (docs/decisions/phase-9-notifications.md).
POLICY_VERSION_EXISTS = "This version of the policy has already been published."


def publish_policy_version(
    db: Session,
    kind: str,
    version: str,
    title: str,
    url: str | None,
    published_at: datetime,
    *,
    actor_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> PolicyVersion:
    """Publishes a new version of the Terms of Service, Privacy Policy or Health Consent, which
    every client must accept again (story 12.2). Commits.

    When it takes effect (straight away, or at a later `published_at` through a job), every
    client's signed-in sessions end, so they see the update first the next time they open the
    app, and every client is emailed, in batches. The publication is audited, with the admin as
    `actor_id` once Phase A passes one.

    Asking for an updated Health Consent again for the client's own profile and each family
    member and invited teen is the conversations package's (see
    docs/decisions/phase-9-notifications.md)."""
    if kind not in POLICY_KINDS:
        raise ValueError(f"Unknown policy kind: {kind}")
    if published_at.tzinfo is None:
        raise ValueError("published_at needs a time zone.")
    policy = PolicyVersion(
        kind=kind, version=version, title=title, url=url, published_at=published_at
    )
    with database_errors_retryable(db):
        try:
            db.add(policy)
            db.flush()
        except IntegrityError:
            db.rollback()
            raise AppError(409, "policy_version_exists", POLICY_VERSION_EXISTS, "version") from None
        audit.record(
            db,
            "policy.published",
            actor_id=actor_id,
            target_type="policy_version",
            target_id=policy.id,
            request=request,
            details={"kind": kind, "version": version, "published_at": published_at.isoformat()},
        )
        if published_at <= _now():
            announce_policy_version(db, policy)
        else:
            jobs.enqueue(
                db,
                notifications.ANNOUNCE_POLICY_JOB,
                {"policy_version_id": str(policy.id)},
                run_at=published_at,
            )
        db.commit()
    return policy


def announce_policy_version(db: Session, policy: PolicyVersion) -> None:
    """Story 12.2, once a version takes effect: ends every client's signed-in sessions and
    starts the update emails. Caller commits.

    The sessions end with no `revoked_reason`, so the apps get the general "signed out" message
    and show the updated policy before Sign In. Their push devices stop getting pushes until
    they sign in again. Teens' sessions end too; Phase 3b's access gate pauses them until the
    parent accepts."""
    ended = db.execute(
        update(UserSession)
        .where(
            UserSession.revoked_at.is_(None),
            UserSession.user_id.in_(select(User.id).where(User.role == "client")),
        )
        .values(revoked_at=_now())
        .execution_options(synchronize_session=False)
    ).rowcount
    audit.record(
        db,
        "policy.announced",
        target_type="policy_version",
        target_id=policy.id,
        details={"kind": policy.kind, "version": policy.version, "sessions_ended": ended},
    )
    notifications.start_policy_update_emails(db, policy)
