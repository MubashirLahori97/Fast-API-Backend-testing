"""Teens with their own account (stories 1.5, 1.6, 2.3, 2.4, and the teen parts of 3.2, 8.1,
8.2, 11.3, 11.4 and 12.1). The decisions are in docs/decisions/phase-3b-teens.md.

- The parent invites from the family intake (2.2): the draft whose Teen Profile Choice is
  "own_account" becomes a TeenLink, which holds only what the parent typed, and the draft is
  deleted. The invite takes a family place at once (8.1), checked under the account lock.
- The teen opens the link, gives their name, date of birth, city, state and country and a
  password (the email is the invite's, locked), and their own account is made with
  `account_type = 'teen'` and their own profile. No code (the link proves the address), no
  policies and no trial: the parent gave consent and pays. Then the teen onboarding (2.3) runs
  on that profile with the usual self intake endpoints.
- The access gate is app/teens/access.py. Paused teens keep Privacy & Data.
- At the age of majority (1.6) the teen account stops. Create My Account turns it into an
  adult account in place (question 39): the history never moves, so it can't be seen from two
  accounts, and a failed move can't lose it. The parent's place is freed and they're told.

Nothing here tells the parent anything about the teen's health or activity, and the parent's
notices about a teen name them only with the first name the parent typed.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

from fastapi import Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.auth import emails as auth_emails
from app.auth import service as auth_service
from app.auth.models import User
from app.auth.security import hash_password, hash_secret, new_token
from app.billing import catalog, entitlements
from app.conversations.models import Escalation
from app.core import audit, jobs
from app.core.ages import HAWAII, TEEN_FROM_AGE, age_on, us_today, years_before
from app.core.config import settings
from app.core.email import SendEmail
from app.core.errors import ACTION_FAILED, AppError
from app.core.jobs import Job
from app.notifications import emails as notification_emails
from app.notifications import service as notifications
from app.privacy.teens import AGE_OF_MAJORITY_REACHED
from app.profiles.models import Profile
from app.teens import access
from app.teens.models import TeenAccount, TeenLink, TeenParentNotice
from app.teens.schemas import (
    TEEN_EMAIL_INVALID,
    AdultAccountBody,
    AdultAccountCreated,
    AdultAccountOut,
    InvitedTeenOut,
    TeenInviteBody,
    TeenInviteOut,
    TeenInviteSent,
    TeenLinkResult,
    TeenSignedUp,
    TeenSignUpBody,
)

AGE_CHECK_JOB = "teens.age_check"  # see app/teens/jobs.py
# Key for pg_advisory_xact_lock, so two workers starting at once don't both queue the check.
AGE_CHECK_LOCK_KEY = 9_120_503

# Story 1.5's messages.
INVITE_EXPIRED = "This invite has expired. Please ask your parent or guardian to send a new one."
WELCOME_TITLE = "Welcome to Your Oracle"
WELCOME = (
    "This is your own private space to learn about your health. Ask me anything you’re curious "
    "about, and I’ll help you understand what’s going on and what you can talk about with your "
    "provider."
)
# Story 1.6's, and 2.4's free trial line.
HISTORY_MOVED = "Your history has been moved to your new account."
HISTORY_MOVE_FAILED = "We couldn’t move your history just now. We’ll try again shortly."
# Story 12.2's.
ALL_SET = "Thanks, you’re all set."

# Not in the stories (docs/decisions/phase-3b-teens.md).
LINK_NOT_FOUND = "We couldn’t find that family member."
ALREADY_INVITED = (
    "You’ve already invited this email address. You can send the invite again from Manage Family."
)
ALREADY_JOINED = "{name} has already joined, so there’s no invite to send."
RESEND_TOO_SOON = "Please wait a minute before sending the invite again."
UNDER_13 = (
    "Your Oracle accounts are for teens aged 13 and over. Please ask your parent or guardian to "
    "set up your profile for you."
)
ADULT_AGE = (
    "You’ve reached adult age, so you can create your own Your Oracle account. Please sign up "
    "instead."
)
NOT_A_TEEN_ACCOUNT = "This invite can only be used with a teen account."
ALREADY_LINKED = "Your account is already linked to a Family plan."
LINKED = "You’re linked to your parent’s or guardian’s Family plan again."
NOT_AGED_OUT = "This is only for teen accounts that have reached adult age."
NOT_OF_AGE_IN_STATE = "You haven’t reached adult age in this state yet."


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _saving(db: Session, message: str = ACTION_FAILED) -> Iterator[None]:
    """database_errors_retryable with a message of the caller's choice. The database's text isn't
    returned or logged: it can hold the row's values."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", message) from None


def _health_consent_for(name: str) -> str:
    """Story 12.2's "Health Consent for a family member not confirmed"."""
    return f"Please confirm the updated Health Consent for {name} to continue."


def _invite_link(token: str) -> str:
    return f"{settings.teen_invite_url}#token={token}"


def _send_invite(send: SendEmail, email: str, token: str) -> None:
    send(notification_emails.teen_invite(email, _invite_link(token)))


def _audit_link(
    db: Session,
    action: str,
    link: TeenLink,
    actor_id: uuid.UUID | None,
    request: Request | None = None,
    details: dict | None = None,
) -> None:
    """Ids only: never the teen's name or email."""
    audit.record(
        db,
        action,
        actor_id=actor_id,
        target_type="teen_link",
        target_id=link.id,
        request=request,
        details=details,
    )


# The parent's side: cards, the invite, and Manage Family's actions (stories 1.5, 8.1, 8.2)


def card(db: Session, link: TeenLink, parent: User) -> InvitedTeenOut:
    name = link.first_name
    return InvitedTeenOut(
        id=link.id,
        first_name=name,
        relationship=link.family_relationship,
        status=access.link_status(db, link, parent),
        active=link.turned_off_at is None,
        can_resend=link.teen_account_id is None,
        health_consent_needed=access.health_consent_needed(db, link),
        turn_off_confirmation=(
            f"Turn off {name}’s access? They won’t be able to use Your Oracle until you turn it "
            "back on. Their information will be kept."
        ),
        remove_confirmation=(
            f"Remove {name} from your family? {name} will have 10 days to keep using Your Oracle "
            "and download their information. After that, their account and information will be "
            "deleted."
        ),
    )


def _links(db: Session, parent: User) -> list[TeenLink]:
    return list(
        db.scalars(
            select(TeenLink)
            .where(TeenLink.parent_account_id == parent.id)
            .order_by(TeenLink.created_at)
        )
    )


def cards(db: Session, parent: User) -> list[InvitedTeenOut]:
    """Manage Family's invited teen cards (8.2), in the order they were invited."""
    return [card(db, link, parent) for link in _links(db, parent)]


def joined_names(db: Session, parent: User) -> list[str]:
    """The first names (as the parent typed them) of the teens who joined, for 11.4's
    "[Name] has their own account..."."""
    return [link.first_name for link in _links(db, parent) if link.teen_account_id is not None]


def _owned_link(db: Session, link_id: uuid.UUID, parent: User, *, lock: bool = False) -> TeenLink:
    """Another parent's link gets the same 404 as an unknown one."""
    link = db.get(TeenLink, link_id, with_for_update=lock, populate_existing=lock)
    if link is None or link.parent_account_id != parent.id:
        raise AppError(404, "teen_link_not_found", LINK_NOT_FOUND)
    return link


def check_can_invite(account: User, name: str | None) -> None:
    """Story 1.5: "Only parents on the Family plan can invite a teen to their own account", with
    1.5's upgrade prompt (asked when the Teen Profile Choice is saved, and again at the invite).
    A teen account can't invite anyone (8.1). The places are checked when the invite is sent."""
    if access.is_teen_account(account):
        raise AppError(403, "teen_account", entitlements.TEEN_ACCOUNT_NO_FAMILY)
    if entitlements.plan(account) != "family":
        raise AppError(
            403,
            "family_plan_required",
            "Inviting your teen to their own account is part of the Family plan. "
            f"Upgrade to invite {name or 'your teen'}.",
            "teen_profile_choice",
        )


def start_invite(
    db: Session,
    draft: Profile,
    parent: User,
    body: TeenInviteBody,
    send: SendEmail,
    request: Request,
) -> TeenInviteSent:
    """Story 1.5 (and 2.2's "Teen with their own account"): the parent accepted the privacy
    disclaimer and typed the teen's email. The draft becomes a TeenLink holding the first name,
    the relationship and the email; the date of birth the parent typed only decided that the
    Teen Profile Choice applied, and goes with the draft. The invite takes a family place from
    now (8.1), and the current Health Consent is recorded as the parent's consent for the teen
    (3.1: the parent gave consent)."""
    from app.profiles import service as profiles  # app.profiles imports this package

    with _saving(db):
        # The draft first, then the account: the same order as completing an intake.
        db.refresh(draft, with_for_update=True)
        name = draft.first_name
        if draft.is_self or draft.intake_completed_at is not None:
            raise AppError(
                409,
                "not_family_draft",
                "Please start by adding a family member, then choose Teen with their own account.",
            )
        missing = profiles.next_question(draft)
        if missing != "teen_invite":
            # An earlier step isn't answered, or the choice isn't "own_account": the intake's
            # own message for it, e.g. 2.2's "Please choose how you’d like to set up [Name]’s
            # profile."
            message = profiles._missing_answer_message(draft, missing)
            if missing not in ("family_relationship", "first_name", "date_of_birth"):
                message = f"Please choose how you’d like to set up {name}’s profile."
                missing = "teen_profile_choice"
            raise AppError(409, "teen_choice_required", message, missing)
        db.refresh(parent, with_for_update=True)
        check_can_invite(parent, name)
        entitlements.check_can_add_family_member(db, parent, name)  # a place must be free (8.1)
        if body.email == parent.email:
            raise AppError(422, "validation_error", TEEN_EMAIL_INVALID, "email")
        existing = db.scalar(
            select(TeenLink.id).where(
                TeenLink.parent_account_id == parent.id, TeenLink.email == body.email
            )
        )
        if existing is not None:
            raise AppError(409, "already_invited", ALREADY_INVITED, "email")
        consent_id = access.current_health_consent_id(db)
        if consent_id is None:
            # Seeded by a migration, so this is a broken deployment. Never skip the consent.
            raise AppError(503, "health_consent_unavailable", ACTION_FAILED)

        now = _now()
        token = new_token()
        link = TeenLink(
            parent_account_id=parent.id,
            first_name=name,
            family_relationship=draft.family_relationship,
            email=body.email,
            token_hash=hash_secret(token),
            invite_sent_at=now,
            invite_expires_at=now + timedelta(days=settings.teen_invite_days),
            health_consent_version_id=consent_id,
            health_consent_at=now,
        )
        try:
            db.add(link)
            db.flush()
        except IntegrityError:  # the same email invited twice at once
            db.rollback()
            raise AppError(409, "already_invited", ALREADY_INVITED, "email") from None
        db.execute(
            delete(Profile).where(Profile.id == draft.id, Profile.intake_completed_at.is_(None))
        )
        _audit_link(
            db,
            "teen.invited",
            link,
            parent.id,
            request,
            {"health_consent_version": str(consent_id)},
        )
        db.commit()
    _send_invite(send, link.email, token)
    return TeenInviteSent(
        invited_teen=card(db, link, parent),
        message=(
            f"Invitation sent. We’ve emailed {link.email} with instructions to create their "
            "Oracle account."
        ),
    )


def resend_invite(
    db: Session, link_id: uuid.UUID, parent: User, send: SendEmail, request: Request
) -> TeenLinkResult:
    """Story 8.2's Resend invite: a new link is emailed and the old one stops working. Also the
    way to renew an expired invite (1.5)."""
    with _saving(db):
        link = _owned_link(db, link_id, parent, lock=True)
        if link.teen_account_id is not None:
            raise AppError(409, "already_joined", ALREADY_JOINED.format(name=link.first_name))
        now = _now()
        if now - link.invite_sent_at < timedelta(seconds=settings.code_resend_seconds):
            raise AppError(429, "resend_too_soon", RESEND_TOO_SOON)
        token = new_token()
        link.token_hash = hash_secret(token)
        link.invite_sent_at = now
        link.invite_expires_at = now + timedelta(days=settings.teen_invite_days)
        _audit_link(db, "teen.invite_resent", link, parent.id, request)
        email = link.email
        db.commit()
    _send_invite(send, email, token)
    return TeenLinkResult(
        invited_teen=card(db, link, parent),
        message=f"We’ve sent {link.first_name} a new invite.",
    )


def _tell_teen_paused(db: Session, link: TeenLink) -> None:
    """Story 12.1's access-paused notice, to the teen. Caller commits."""
    if link.teen_account_id is None:
        return
    teen = db.get(User, link.teen_account_id)
    if teen is not None and access.is_teen_account(teen):
        notifications.notify(db, teen, "access_paused")


def turn_off(db: Session, link_id: uuid.UUID, parent: User, request: Request) -> TeenLinkResult:
    """Story 8.2: the place is freed, the teen sees only Privacy & Data until it's turned back on,
    and their information is kept. Turning off a teen who's already off changes nothing."""
    with _saving(db):
        link = _owned_link(db, link_id, parent, lock=True)
        db.refresh(parent, with_for_update=True)
        if link.turned_off_at is None:
            link.turned_off_at = _now()
            link.plan_paused_at = None
            _audit_link(db, "teen.turned_off", link, parent.id, request)
            _tell_teen_paused(db, link)
            db.commit()
    return TeenLinkResult(
        invited_teen=card(db, link, parent), message=f"{link.first_name}’s access is turned off."
    )


def turn_on(db: Session, link_id: uuid.UUID, parent: User, request: Request) -> TeenLinkResult:
    """Story 8.2: needs a free place on the Family plan, like a managed member (the upgrade or
    add-on prompt otherwise). The teen's access comes back with their information intact."""
    with _saving(db):
        link = _owned_link(db, link_id, parent, lock=True)
        db.refresh(parent, with_for_update=True)
        if link.turned_off_at is not None:
            entitlements.check_can_turn_on_family_member(db, parent, link.first_name)
            link.turned_off_at = None
            link.plan_paused_at = None
            _audit_link(db, "teen.turned_on", link, parent.id, request)
            db.commit()
    return TeenLinkResult(
        invited_teen=card(db, link, parent), message=f"{link.first_name}’s access is turned on."
    )


def remove(db: Session, link_id: uuid.UUID, parent: User, request: Request) -> str:
    """Story 8.2's Remove for an invited teen (6 Nov 19:22): the place is freed straight away,
    and the link goes. A teen who joined gets an Invited Teen Removal deletion request: they're
    told, keep full use of their account for the 10-day grace period (access.in_removal_grace),
    and are then locked; the team deletes their account and data within 45 calendar days of the
    removal (app/privacy/service.py). A pending invite's link just stops working.

    Lock order: the link, the parent's account, then the teen's account."""
    from app.privacy import service as privacy  # app.privacy imports app.accounts, like this

    with _saving(db):
        link = _owned_link(db, link_id, parent, lock=True)
        db.refresh(parent, with_for_update=True)
        name = link.first_name
        teen_id = link.teen_account_id
        _audit_link(
            db,
            "teen.removed",
            link,
            parent.id,
            request,
            {"joined": teen_id is not None},
        )
        db.delete(link)
        db.flush()
        if teen_id is not None:
            privacy.request_teen_removal(db, parent, teen_id, request)
        db.commit()
    return f"{name} has been removed from your family."


def confirm_health_consent(
    db: Session,
    link_id: uuid.UUID,
    parent: User,
    policy_version_id: uuid.UUID | None,
    request: Request,
) -> TeenLinkResult:
    """Story 12.2: after an updated Health Consent, the parent confirms it as medical advocate for
    each invited teen. Until then that teen is paused; once it's recorded, their access is back.
    Only the current version counts."""
    with _saving(db):
        link = _owned_link(db, link_id, parent, lock=True)
        current = access.current_health_consent_id(db)
        if current is None:
            raise AppError(503, "health_consent_unavailable", ACTION_FAILED)
        message = _health_consent_for(link.first_name)
        if policy_version_id is None:
            raise AppError(422, "health_consent_required", message, "policy_version_id")
        if policy_version_id != current:
            # A newer version was published since the app showed it: the app shows that one.
            raise AppError(409, "health_consent_outdated", message, "policy_version_id")
        if link.health_consent_version_id != current:
            link.health_consent_version_id = current
            link.health_consent_at = _now()
            _audit_link(
                db,
                "teen.health_consent_confirmed",
                link,
                parent.id,
                request,
                {"health_consent_version": str(current)},
            )
            db.commit()
    return TeenLinkResult(invited_teen=card(db, link, parent), message=ALL_SET)


# The teen's side: the invite link and their own account (story 1.5)


def _reject(db: Session, request: Request, reason: str) -> AppError:
    """Recorded (no target), so the per-IP limit counts made-up and old tokens."""
    audit.record(db, "teen.invite_rejected", request=request, details={"reason": reason})
    db.commit()
    return AppError(400, "invite_expired", INVITE_EXPIRED, "token")


def _open_invite(db: Session, token: str, request: Request, *, lock: bool = False) -> TeenLink:
    stmt = select(TeenLink).where(TeenLink.token_hash == hash_secret(token))
    if lock:
        stmt = stmt.with_for_update()
    link = db.scalar(stmt)
    if link is None:
        raise _reject(db, request, "unknown")
    if link.teen_account_id is not None or link.invite_expires_at <= _now():
        raise _reject(db, request, "expired")
    return link


def check_invite(db: Session, token: str, request: Request) -> TeenInviteOut:
    """Story 1.5: the link opens the teen setup, not the normal sign-up, with the email filled in
    and locked. An expired, used or made-up link gets 1.5's "This invite has expired...". If the
    email already has an account, the app sends the teen to Sign In."""
    auth_service.check_ip_limit(db, request, "teen.invite_rejected")
    link = _open_invite(db, token, request)
    exists = db.scalar(select(User.id).where(User.email == link.email)) is not None
    return TeenInviteOut(email=link.email, first_name=link.first_name, account_exists=exists)


def _check_teen_age(date_of_birth: date, state: str) -> None:
    """Story 1.5's age and eligibility check: only the teen category (13 up to the age of
    majority) continues. Younger children are parent-managed only (2.2), and an adult signs up
    on their own (1.1). Question 22 asks what the BA wants here."""
    if age_on(date_of_birth, us_today()) < TEEN_FROM_AGE:
        raise AppError(422, "under_13", UNDER_13, "date_of_birth")
    if accounts.adult_in(date_of_birth, state):
        raise AppError(422, "adult_age", ADULT_AGE, "date_of_birth")


def accept_invite(
    db: Session, body: TeenSignUpBody, send: SendEmail, request: Request
) -> TeenSignedUp:
    """Story 1.5's Teen Account Setup. Creates the teen's own account (the invite's email,
    verified by the link) and their own profile, joins the link (the token stops working), and
    signs this device in, trusted like after a code. No policies are recorded and no trial
    starts: the parent gave consent and pays."""
    auth_service.check_ip_limit(db, request, "teen.invite_rejected")
    _open_invite(db, body.token, request)  # fast refusal before the age check and the hashing
    _check_teen_age(body.date_of_birth, body.state)
    password_hash = hash_password(body.password)
    with _saving(db):
        link = _open_invite(db, body.token, request, lock=True)
        if db.scalar(select(User.id).where(User.email == link.email)) is not None:
            raise AppError(409, "email_taken", auth_service.EMAIL_TAKEN, "email")
        now = _now()
        teen = User(
            role="client",
            account_type="teen",
            email=link.email,
            first_name=body.first_name,
            date_of_birth=body.date_of_birth,
            country=body.country,
            state=body.state,
            password_hash=password_hash,
            email_verified_at=now,
            # No trial: access follows the parent's Family plan. The column needs a value.
            trial_ends_at=now,
            password_changed_at=now,
        )
        db.add(teen)
        try:
            db.flush()
        except IntegrityError:  # an account with this email appeared meanwhile
            db.rollback()
            raise AppError(409, "email_taken", auth_service.EMAIL_TAKEN, "email") from None
        db.add(TeenAccount(account_id=teen.id, city=body.city, joined_at=now))
        # The teen's own profile, which the teen onboarding (2.3) fills in. The parent never
        # holds it.
        profile = Profile(account_id=teen.id, is_self=True, date_of_birth=teen.date_of_birth)
        db.add(profile)
        db.flush()
        link.teen_account_id = teen.id
        link.joined_at = now
        link.token_hash = None
        audit.record(
            db,
            "auth.signed_up",
            actor_id=teen.id,
            target_type="user",
            target_id=teen.id,
            request=request,
            details={"source": "teen_invite"},
        )
        audit.record(db, "auth.email_verified", actor_id=teen.id, request=request)
        _audit_link(db, "teen.joined", link, teen.id, request)
        audit.record(
            db,
            "profile.created",
            actor_id=teen.id,
            target_type="profile",
            target_id=profile.id,
            request=request,
            details={"is_self": True},
        )
        # auth.service's step after a right code: this device is trusted and gets a session.
        signed_in = auth_service._sign_in_after_code(db, teen, body.platform, request)
        db.commit()
    send(auth_emails.account_created(teen.email))
    return TeenSignedUp(
        **signed_in.model_dump(),
        profile_id=profile.id,
        welcome_title=WELCOME_TITLE,
        welcome=WELCOME,
    )


def link_existing(db: Session, teen: User, token: str, request: Request) -> str:
    """Story 1.5's "Teen already has an account": the invite sent them to Sign In. A teen account
    that isn't linked to anyone (it was removed from a family, or the parent's account was
    deleted) joins this invite's family. The invite must be for the signed-in account's email."""
    auth_service.check_ip_limit(db, request, "teen.invite_rejected")
    if not access.is_teen_account(teen):
        raise AppError(409, "not_teen_account", NOT_A_TEEN_ACCOUNT)
    with _saving(db):
        db.refresh(teen, with_for_update=True)
        link = _open_invite(db, token, request, lock=True)
        if link.email != teen.email:
            raise _reject(db, request, "other_email")
        if access.reached_majority(teen):
            raise AppError(409, "age_of_majority_reached", AGE_OF_MAJORITY_REACHED)
        if access.link_for_teen(db, teen) is not None:
            raise AppError(409, "already_linked", ALREADY_LINKED)
        link.teen_account_id = teen.id
        link.joined_at = _now()
        link.token_hash = None
        _audit_link(db, "teen.joined", link, teen.id, request, {"existing_account": True})
        try:
            db.commit()
        except IntegrityError:  # linked by another request at the same moment
            db.rollback()
            raise AppError(409, "already_linked", ALREADY_LINKED) from None
    return LINKED


# Hooks for the other packages (billing, privacy, conversations)


def pause_for_plan_end(db: Session, parent: User) -> int:
    """Story 11.3 and 1.5: the parent's Family plan ended. Each joined teen who wasn't turned off
    is paused (the gate already sees the plan), and told; the parent is told for each, with
    nothing about the teen's activity. Marked on the link, so a second run tells nobody twice.
    Returns how many. Caller commits."""
    rows = db.execute(
        update(TeenLink)
        .where(
            TeenLink.parent_account_id == parent.id,
            TeenLink.teen_account_id.is_not(None),
            TeenLink.turned_off_at.is_(None),
            TeenLink.plan_paused_at.is_(None),
        )
        .values(plan_paused_at=_now())
        .returning(TeenLink.id, TeenLink.first_name, TeenLink.teen_account_id)
        .execution_options(synchronize_session=False)
    ).all()
    for link_id, name, teen_id in rows:
        notifications.notify(db, parent, "teen_access_paused", data={"name": name})
        teen = db.get(User, teen_id)
        if teen is not None:
            notifications.notify(db, teen, "access_paused")
        audit.record(
            db,
            "teen.access_paused",
            target_type="teen_link",
            target_id=link_id,
            details={"reason": "family_plan"},
        )
    return len(rows)


def restore_for_plan(db: Session, parent: User) -> int:
    """Story 11.3 and 1.5: the Family plan is active again, so the teens it paused get their
    access back with their history intact, and the parent is told. Teens kept their places all
    along, so there's nothing to fit in. Returns how many. Caller commits."""
    if entitlements.plan(parent) != "family":
        return 0
    rows = db.execute(
        update(TeenLink)
        .where(TeenLink.parent_account_id == parent.id, TeenLink.plan_paused_at.is_not(None))
        .values(plan_paused_at=None)
        .returning(TeenLink.id, TeenLink.first_name, TeenLink.turned_off_at)
        .execution_options(synchronize_session=False)
    ).all()
    restored = 0
    for link_id, name, turned_off_at in rows:
        if turned_off_at is not None:
            continue  # the parent turned them off meanwhile: still off
        notifications.notify(db, parent, "teen_access_restored", data={"name": name})
        audit.record(
            db,
            "teen.access_restored",
            target_type="teen_link",
            target_id=link_id,
            details={"reason": "family_plan"},
        )
        restored += 1
    return restored


def _joined_links(db: Session, parent_id: uuid.UUID) -> list[TeenLink]:
    return list(
        db.scalars(
            select(TeenLink).where(
                TeenLink.parent_account_id == parent_id,
                TeenLink.teen_account_id.is_not(None),
                TeenLink.turned_off_at.is_(None),
            )
        )
    )


def pause_for_revoked_consent(db: Session, parent: User) -> None:
    """Story 11.4: the parent revoked consent, so their invited teens lose access until it's
    given again; each teen is told. The gate sees the revocation itself, so nothing is stored.
    Caller commits."""
    for link in _joined_links(db, parent.id):
        _tell_teen_paused(db, link)
        audit.record(
            db,
            "teen.access_paused",
            target_type="teen_link",
            target_id=link.id,
            details={"reason": "consent"},
        )


def joined_teen_accounts(db: Session, parent_id: uuid.UUID) -> list[uuid.UUID]:
    """Story 11.4 (6 Nov 19:22): the accounts of the teens who joined this parent's family,
    turned off or not. An Account Deletion deletes them with the parent's account; their links
    go with it (ON DELETE CASCADE)."""
    return list(
        db.scalars(
            select(TeenLink.teen_account_id)
            .where(
                TeenLink.parent_account_id == parent_id,
                TeenLink.teen_account_id.is_not(None),
            )
            .order_by(TeenLink.teen_account_id)
        )
    )


def remove_from_family(db: Session, teen_id: uuid.UUID) -> None:
    """Story 11.4: the teen's own deletion was completed. They leave the parent's family and the
    place is freed; the parent isn't told why. Caller commits."""
    link = db.scalar(select(TeenLink).where(TeenLink.teen_account_id == teen_id))
    if link is None:
        return
    _audit_link(db, "teen.removed_from_family", link, None)
    db.delete(link)


def tell_parent(db: Session, escalation: Escalation) -> None:
    """Story 3.2: a teen with their own account had an emergency or a crisis. The parent is told
    their teen may need help, with the first name the parent typed and nothing from the
    conversation. Runs in the transaction that records the escalation, which commits; push and
    email go out straight after (12.1's "Teen safety notifications are sent straight away"), with
    a name-free text. A teen who's no longer linked to anyone has no parent to tell."""
    if escalation.profile_type != "teen" or escalation.level not in ("emergency", "crisis"):
        return
    link = db.scalar(select(TeenLink).where(TeenLink.teen_account_id == escalation.account_id))
    if link is None:
        return
    parent = db.get(User, link.parent_account_id)
    if parent is None:
        return
    kind = (
        "teen_may_need_urgent_help" if escalation.level == "emergency" else "teen_may_need_support"
    )
    sent = notifications.notify(db, parent, kind, data={"name": link.first_name})
    if sent is None:
        return  # the parent's notifications are stopped (consent revoked, or deactivated)
    db.add(TeenParentNotice(escalation_id=escalation.id, told_at=_now()))
    # No actor, level or names, like escalation.recorded.
    audit.record(db, "teen.parent_told", target_type="escalation", target_id=escalation.id)


# Story 1.6 and 2.4: reaching the age of majority


def _adult_account_check(db: Session, teen: User) -> None:
    if not access.is_teen_account(teen) or not access.reached_majority(teen):
        raise AppError(409, "not_aged_out", NOT_AGED_OUT)
    if accounts.open_account_deletion(db, teen) is not None:
        raise AppError(409, "deletion_requested", accounts.ALREADY_SCHEDULED)


def adult_account_details(db: Session, teen: User) -> AdultAccountOut:
    """Story 1.6's Create My Account: the adult sign-up, with the first name, date of birth and
    email from the teen account."""
    _adult_account_check(db, teen)
    return AdultAccountOut(
        message=AGE_OF_MAJORITY_REACHED,
        first_name=teen.first_name,
        date_of_birth=teen.date_of_birth,
        email=teen.email,
        country=teen.country or "US",
        state=teen.state,
        policies=accounts.current_policies(db),
    )


def create_adult_account(
    db: Session, teen: User, body: AdultAccountBody, request: Request
) -> AdultAccountCreated:
    """Stories 1.6 and 2.4, built as question 39's proposal: the teen account becomes the new
    adult account in place. Its conversations, health profile, sex at birth, gender and pronouns
    stay where they are, so the history is all there, is never visible from two accounts, and
    can't be lost half-way (a failed save changes nothing, and the teen tries again).

    - The Terms of Service and Privacy Policy are accepted, as at 1.1's sign-up. The adult
      Health Consent is asked at the next message for their own profile (3.1).
    - The 14-day free trial starts now (2.4).
    - The parent's link goes: the place is free, and the parent is told (12.1).
    - The teen-only details (TeenAccount) are deleted."""
    _adult_account_check(db, teen)
    if not accounts.adult_in(teen.date_of_birth, body.state):
        raise AppError(422, "not_of_age", NOT_OF_AGE_IN_STATE, "state")
    with _saving(db, HISTORY_MOVE_FAILED):
        # The account, then its link: the same order as the purge and link_existing.
        db.refresh(teen, with_for_update=True)
        _adult_account_check(db, teen)
        link = access.link_for_teen(db, teen, lock=True)
        now = _now()
        teen.account_type = "adult"
        teen.first_name = body.first_name
        teen.state = body.state
        teen.trial_ends_at = now + timedelta(days=catalog.trial_days())
        accounts.record_acceptances(db, teen, accounts.current_policies(db), request)
        notifications.cancel_scheduled(db, teen, kind="age_of_majority_reminder")
        if link is not None:
            parent = db.get(User, link.parent_account_id)
            _audit_link(db, "teen.left_family", link, teen.id, request, {"reason": "adult_account"})
            if parent is not None:
                notifications.notify(db, parent, "teen_own_account", data={"name": link.first_name})
            db.delete(link)
        db.execute(delete(TeenAccount).where(TeenAccount.account_id == teen.id))
        audit.record(
            db,
            "teen.adult_account_created",
            actor_id=teen.id,
            target_type="user",
            target_id=teen.id,
            request=request,
            details={"history": "kept_in_place"},
        )
        db.commit()
    from app.profiles import service as profiles  # app.profiles imports this package

    if profiles.needs_intake(db, teen):
        resume = profiles.profile_to_resume(db, teen)
        step, profile_id = "intake", resume.id if resume else None
    else:
        default = profiles.default_profile(db, teen)
        step, profile_id = "dashboard", default.id if default else None
    return AdultAccountCreated(
        message=HISTORY_MOVED,
        trial_message=(
            f"Your {catalog.trial_days()}-day free trial has started. Choose a plan anytime to "
            "unlock everything."
        ),
        trial_ends_at=teen.trial_ends_at,
        next_step=step,
        profile_id=profile_id,
    )


def _reminder_day(date_of_birth: date, state: str | None) -> date:
    """Two weeks before the age of majority in the teen's own state."""
    return access.adult_on(date_of_birth, state) - timedelta(days=settings.teen_age_reminder_days)


def run_age_check(db: Session, now: datetime) -> None:
    """Story 1.6's daily age check, on Hawaii's date:

    - two weeks before the age of majority, the reminder is handed to notifications.schedule for
      09:00 in Hawaii that day (a reminder missed while the worker was down is still sent within
      `reminder_catch_up_days`, and not after: its "in two weeks" would be wrong);
    - on the day, the teen account stops: recorded once in the audit log. The gate already
      works from the date of birth, so the teen sees Create My Account at their next request.

    Only teens within the reminder window are read. Commits."""
    day = us_today()
    # The youngest age of majority in any state, so this rough filter misses nobody; each teen
    # is then checked against their own state's age.
    youngest_majority = min([settings.age_of_majority, *settings.age_of_majority_by_state.values()])
    soon_adult = years_before(
        day + timedelta(days=settings.teen_age_reminder_days), youngest_majority
    )
    rows = db.execute(
        select(User, TeenAccount)
        .join(TeenAccount, TeenAccount.account_id == User.id)
        .where(
            User.account_type == "teen",
            User.date_of_birth <= soon_adult,
            or_(TeenAccount.aged_out_at.is_(None), TeenAccount.reminder_scheduled_at.is_(None)),
        )
        .with_for_update(of=TeenAccount, skip_locked=True)
    ).all()
    for teen, details in rows:
        if access.reached_majority(teen):
            if details.aged_out_at is None:
                details.aged_out_at = now
                audit.record(db, "teen.account_stopped", target_type="user", target_id=teen.id)
            details.reminder_scheduled_at = details.reminder_scheduled_at or now
            continue
        if details.reminder_scheduled_at is not None:
            continue
        first_day = _reminder_day(teen.date_of_birth, teen.state)
        last_day = first_day + timedelta(days=settings.reminder_catch_up_days)
        if not first_day <= day <= last_day:
            continue
        send_at = datetime.combine(day, time(settings.teen_age_reminder_hour_hawaii), tzinfo=HAWAII)
        notifications.schedule(db, teen, "age_of_majority_reminder", max(send_at, now))
        details.reminder_scheduled_at = now
        audit.record(db, "teen.age_reminder_scheduled", target_type="user", target_id=teen.id)
    db.commit()


def next_age_check_at() -> datetime:
    """Five minutes after the next midnight in Hawaii."""
    return datetime.combine(us_today() + timedelta(days=1), time(0, 5), tzinfo=HAWAII)


def ensure_age_check(db: Session, run_at: datetime | None = None) -> None:
    """Makes sure one age check is waiting to run. Caller commits."""
    db.execute(select(func.pg_advisory_xact_lock(AGE_CHECK_LOCK_KEY)))
    waiting = db.scalar(
        select(Job.id).where(Job.kind == AGE_CHECK_JOB, Job.status == "pending").limit(1)
    )
    if waiting is None:
        jobs.enqueue(db, AGE_CHECK_JOB, run_at=run_at)


# For the admin panel (Super Admin 2.1, 3.1 and 4.1). Names only as the parent typed them.


def admin_invited_teens(db: Session, parent: User) -> list[dict]:
    """Client Details' invited teens: the teen's account id once joined, the first name the
    parent typed, and the card's status. Fits app.admin.clients.schemas.InvitedTeenOut."""
    return [
        {
            "account_id": link.teen_account_id,
            "first_name": link.first_name,
            "status": access.link_status(db, link, parent),
        }
        for link in _links(db, parent)
    ]


def admin_teen_link(db: Session, teen: User) -> dict | None:
    """A teen's Client Details: the parent's account and first name, and whether the teen's access
    is paused. Fits app.admin.clients.schemas.TeenLinkOut; None when not linked."""
    if not access.is_teen_account(teen):
        return None
    link = access.link_for_teen(db, teen)
    if link is None:
        return None
    parent = db.get(User, link.parent_account_id)
    return {
        "parent_account_id": link.parent_account_id,
        "parent_first_name": parent.first_name if parent is not None else "",
        "access": "active" if access.state(db, teen) == "open" else "paused",
    }


def parent_told_at(db: Session, escalation_id: uuid.UUID) -> datetime | None:
    """Super Admin 4.1: when the parent of a teen with their own account was told."""
    return db.scalar(
        select(TeenParentNotice.told_at).where(TeenParentNotice.escalation_id == escalation_id)
    )


def dashboard_counts(db: Session) -> dict[str, int]:
    """Super Admin 2.1's teen accounts: joined, invite sent (pending invites), and access paused
    (joined teens whose gate is shut, aged-out teens included)."""
    invite_sent = db.scalar(
        select(func.count()).select_from(TeenLink).where(TeenLink.teen_account_id.is_(None))
    )
    teens = list(db.scalars(select(User).where(User.account_type == "teen")))
    paused = sum(1 for teen in teens if access.state(db, teen) != "open")
    return {"joined": len(teens), "invite_sent": invite_sent, "access_paused": paused}
