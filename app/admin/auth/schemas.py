"""Request and response bodies for an invited Admin's account setup (Admin 1.1).

The invite token comes from the link's fragment (`#token=...`) and is always sent in the body,
never in a URL, so it can't reach a server log.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationInfo, field_validator

from app.auth.schemas import PASSWORD_RULES, PASSWORDS_DONT_MATCH
from app.auth.security import meets_password_rules
from app.core.schemas import RequestBody


class InvitationTokenRequest(RequestBody):
    token: str


class InvitationOut(BaseModel):
    """The setup screen: the name and email from the invite, filled in and locked."""

    first_name: str
    last_name: str
    email: str
    expires_at: datetime


class AcceptInvitationRequest(RequestBody):
    token: str
    password: str = ""
    confirm_password: str = ""

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Please create a password.")
        if not meets_password_rules(value):
            raise ValueError(PASSWORD_RULES)
        return value

    @field_validator("confirm_password")
    @classmethod
    def check_confirm_password(cls, value: str, info: ValidationInfo) -> str:
        if not value or ("password" in info.data and value != info.data["password"]):
            raise ValueError(PASSWORDS_DONT_MATCH)
        return value


class SetupCodeRequest(RequestBody):
    token: str
    code: str = ""

    @field_validator("code")
    @classmethod
    def check_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please enter the verification code sent to your email.")
        return value


class SetupCodeSent(BaseModel):
    """The next screen is the Verification screen: a code was emailed to the invite's address
    (Admin 1.1)."""

    status: Literal["verification_required"] = "verification_required"
    expires_in_seconds: int
    # How long until "Resend code" works (60 seconds, settings.code_resend_seconds).
    resend_after_seconds: int
