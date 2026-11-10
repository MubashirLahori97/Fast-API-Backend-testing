"""Request and response bodies for Privacy & Data (story 11.4)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.accounts.schemas import DeletionNoticeOut

DeletionKind = Literal["family_member", "account", "teen_removal", "teen"]
DeletionStatus = Literal[
    "grace_period", "pending", "in_progress", "on_legal_hold", "completed", "declined"
]


class AcceptedPolicyOut(BaseModel):
    kind: Literal["terms", "privacy", "health_consent"]
    title: str
    version: str
    url: str | None
    accepted_at: datetime


class DeletionRequestOut(BaseModel):
    id: uuid.UUID
    kind: DeletionKind
    status: DeletionStatus
    requested_at: datetime
    # The end of the 10-day grace period: the [date] in the messages. Null for a teen's request
    # by email, which has none.
    grace_ends_at: datetime | None
    # 45 calendar days after the request (CCPA/CPRA).
    due_at: datetime


class FamilyMemberName(BaseModel):
    """A managed family member, for the Delete Account disclaimer's list of everyone affected."""

    profile_id: uuid.UUID
    first_name: str


class PrivacyOut(BaseModel):
    """The Privacy & Data screen (story 11.4)."""

    account_type: Literal["adult", "teen"]
    # The Terms of Service, Privacy Policy and Health Consent the client accepted, each at its
    # latest accepted version, with the date.
    accepted_policies: list[AcceptedPolicyOut]
    consent_revoked: bool
    # False for a teen with their own account (the parent gave consent), once it's revoked, and
    # while a deletion of the account is open.
    can_revoke_consent: bool
    # This account's own open request to delete it (an Account Deletion, a teen's own, or the
    # parent's removal of a teen).
    deletion_request: DeletionRequestOut | None
    # During a grace period, including the parent's when the account is an invited teen's.
    deletion_notice: DeletionNoticeOut | None
    # Everyone the Delete Account disclaimer names: the managed family members, and the invited
    # teens who joined (their first names as the parent typed them).
    family_members: list[FamilyMemberName]
    invited_teens: list[str]
    # Story 11.4's texts for the Delete Account flow: "Would you like to export your data before
    # deleting your account?", the confirmation (the teen's for a teen account), and the
    # disclaimer when there are family members or invited teens (null otherwise).
    export_first: str
    delete_confirmation: str
    delete_disclaimer: str | None


class DeletionRequested(BaseModel):
    # "Your account is scheduled for deletion on [date]."
    message: str
    deletion_request: DeletionRequestOut
