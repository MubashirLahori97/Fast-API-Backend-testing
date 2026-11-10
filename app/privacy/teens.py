"""What Privacy & Data, the policy gate and the purge need to know about invited teens with their
own account (stories 1.5, 1.6 and 11.4). The work is in app/teens/; these keep the callers'
names, and import app/teens inside each function because app.accounts.service imports this
module and app/teens imports app.accounts.service.

Story 11.4's rules they carry:

- revoking consent pauses the parent's invited teens, and giving it again restores them; their
  data is kept;
- deleting the parent's account deletes their invited teens' accounts and data too, after the
  same 10-day grace period, during which the teens keep full use (6 Nov 19:22 stories);
- a teen the parent removed keeps full use for the removal's 10-day grace period, though they
  aren't linked any more, and is then locked and deleted (8.2);
- a teen who has lost access sees only Privacy & Data, with ACCESS_PAUSED;
- a teen's own deletion, once completed, removes them from the parent's family and frees the
  place, and the parent isn't told why.
"""

import uuid

from sqlalchemy.orm import Session

from app.auth.models import User

# Story 11.4 (and 1.2, 1.5, 8.2, 12.2 since 5 Nov): what a teen who has lost access sees. The
# long version everywhere (docs/PLAN.md, question 48).
ACCESS_PAUSED = (
    "Your access is paused. Please ask your parent or guardian. You can still download your "
    "data or ask for it to be deleted here."
)
# Story 1.6: what a teen who has reached the age of majority sees, with Create My Account.
AGE_OF_MAJORITY_REACHED = (
    "You’ve reached adult age, so this account is no longer available. Please create your own "
    "account to continue."
)


def access_paused(db: Session, account: User) -> bool:
    """True for an invited teen who has lost access: removed, turned off, the Family plan
    ended, the parent revoked consent or hasn't accepted updated policies or the updated Health
    Consent for them (app/teens/access.py). The policy gate then lets them use only Privacy &
    Data."""
    if account.account_type != "teen":
        return False
    from app.teens import access

    return access.state(db, account) == "paused"


def age_of_majority_reached(db: Session, account: User) -> bool:
    """True for a teen account whose owner has reached the age of majority (story 1.6). They
    can't use it any more, except Privacy & Data, and see Create My Account."""
    if account.account_type != "teen":
        return False
    from app.teens import access

    return access.state(db, account) == "aged_out"


def lost_access(db: Session, account: User) -> bool:
    """A teen account that can't use the app now (paused, or at the age of majority). Only the
    teen's safety and access notices reach it meanwhile (12.1, 11.4)."""
    if account.account_type != "teen":
        return False
    from app.teens import access

    return access.state(db, account) != "open"


def parent_consent_withdrawn(db: Session, teen: User) -> bool:
    """Story 11.4: the parent gave consent for the teen, so the teen's information isn't used
    while the parent's consent is withdrawn (revoked, or the parent's account locked for
    deletion), or when no parent is linked any more, except during the grace period of the
    teen's removal (8.2: full use for 10 days)."""
    from app.accounts import service as accounts
    from app.teens import access

    link = access.link_for_teen(db, teen)
    if link is None:
        return not access.in_removal_grace(db, teen)
    parent = db.get(User, link.parent_account_id)
    return parent is None or accounts.consent_withdrawn(db, parent)


def parent_account_id(db: Session, teen: User) -> uuid.UUID | None:
    """The parent the teen is linked to, if any: an Account Deletion of the parent's account
    deletes the teen's account too (11.4)."""
    from app.teens import access

    link = access.link_for_teen(db, teen)
    return link.parent_account_id if link is not None else None


def invited_teen_names(db: Session, parent: User) -> list[str]:
    """The first names (as the parent typed them) of the parent's teens who joined, for 11.4's
    "[Name] has their own account...". Never their data."""
    from app.teens import service

    return service.joined_names(db, parent)


def pause_for_revoked_consent(db: Session, parent: User) -> None:
    """The parent revoked consent: their invited teens lose access until it's given again (the
    gate sees the revocation), and each teen is told (12.1's access_paused). The caller
    commits."""
    from app.teens import service

    service.pause_for_revoked_consent(db, parent)


def restore_after_consent(db: Session, parent: User) -> None:
    """The parent gave consent again: their invited teens' access comes back with their data
    intact, unless something else still pauses it. The gate works this out on each request, so
    nothing is stored or sent here (12.1 has no "access restored" notice for the teen)."""


def invited_teen_accounts(db: Session, parent_id: uuid.UUID) -> list[uuid.UUID]:
    """The accounts of the teens who joined this parent's family, turned off or not: an Account
    Deletion deletes them with the parent's (11.4, Super Admin 5.2)."""
    from app.teens import service

    return service.joined_teen_accounts(db, parent_id)


def remove_from_family(db: Session, teen_id: uuid.UUID) -> None:
    """A teen's own deletion was completed: they leave the parent's family and the place is
    freed. The parent isn't told why. Called by the purge before the teen's account goes."""
    from app.teens import service

    service.remove_from_family(db, teen_id)
