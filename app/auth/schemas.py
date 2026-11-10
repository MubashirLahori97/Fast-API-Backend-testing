"""Request and response bodies for sign-up, sign-in and passwords.

Error messages are the exact wording from the stories (1.1, 1.2, 1.3, 11.2). Fields default to
empty strings so a missing field gets the story's "please enter..." message, not Pydantic's.
"""

import re
import uuid
from datetime import date
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from app.auth.security import meets_password_rules
from app.core.ages import today, years_before
from app.core.schemas import RequestBody, clean_name
from app.core.zip_codes import zip_in_state

PASSWORD_RULES = (
    "Your password needs at least 8 characters, including an uppercase letter, a lowercase "
    "letter, a number and a special character."
)
PASSWORDS_DONT_MATCH = "The passwords don’t match."
FIELD_REQUIRED = "This field is required."
INVALID_DATE_OF_BIRTH = "Please enter a valid date of birth."
INVALID_STATE = "Please enter a valid state."
# Story 1.1 has both messages: this one for the ZIP code, the one above for the state.
INVALID_STATE_AND_ZIP = "Please enter a valid state and ZIP code."
OLDEST_AGE = 120  # a date of birth further back than this is a typo
# Five digits, or ZIP+4 ("12345-6789"), in every state; the first three digits must belong to
# the state chosen (app/core/zip_codes.py).
ZIP_CODE = re.compile(r"\d{5}(-\d{4})?")

# The 50 states and Washington, D.C. (story 1.1: only the United States can be chosen).
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)

Platform = Literal["web", "mobile"]


def normalize_zip_code(value: str) -> str | None:
    """The ZIP code with spaces taken out, or None when it isn't a valid one."""
    value = "".join(value.split())
    return value if ZIP_CODE.fullmatch(value) else None


def normalize_email(value: str, empty_message: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(empty_message)
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("Please enter a valid email address.") from None
    return value.lower()


# Sign up (story 1.1)


class SignUpDetails(RequestBody):
    """Steps 1 and 2 of sign-up: the date of birth, and the client's state and ZIP code (back
    in the 6 Nov stories). The app can send these to POST /auth/signup/check before step 3,
    so sign-up stops there for anyone under the age of majority, as the story says."""

    date_of_birth: date | None = None
    country: Literal["US"] = "US"
    state: str = ""
    zip_code: str = ""

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def check_date_of_birth(cls, value: object) -> date:
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value.strip())
            except ValueError:
                raise ValueError(INVALID_DATE_OF_BIRTH) from None
        if not isinstance(value, date):
            raise ValueError(INVALID_DATE_OF_BIRTH)
        if value > today() or value < years_before(today(), OLDEST_AGE):
            raise ValueError(INVALID_DATE_OF_BIRTH)
        return value

    @field_validator("state")
    @classmethod
    def check_state(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in US_STATES:
            raise ValueError(INVALID_STATE)
        return value

    @field_validator("zip_code")
    @classmethod
    def check_zip_code(cls, value: str, info: ValidationInfo) -> str:
        """Five digits or ZIP+4, belonging to the state chosen (app/core/zip_codes.py). The
        state is checked first; when it's invalid, its own message is enough."""
        zip_code = normalize_zip_code(value)
        state = info.data.get("state")
        if zip_code is None or (state is not None and not zip_in_state(zip_code, state)):
            raise ValueError(INVALID_STATE_AND_ZIP)
        return zip_code


class SignUpCheck(SignUpDetails):
    """The body of POST /auth/signup/check. Other sign-up fields the app sends with it (the
    first name from step 1, say) are ignored, so the app can send the form as it stands."""

    model_config = ConfigDict(**{**SignUpDetails.model_config, "extra": "ignore"})


class SignUpRequest(SignUpDetails):
    first_name: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""
    accept_terms: bool = False  # the Terms of Service and Privacy Policy checkbox

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str) -> str:
        value = clean_name(value)
        if not value:
            raise ValueError("Please enter your first name.")
        return value

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value, "Email is required.")

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not meets_password_rules(value):
            raise ValueError(PASSWORD_RULES)
        return value

    @field_validator("confirm_password")
    @classmethod
    def check_confirm_password(cls, value: str, info: ValidationInfo) -> str:
        if not value or ("password" in info.data and value != info.data["password"]):
            raise ValueError(PASSWORDS_DONT_MATCH)
        return value

    @field_validator("accept_terms")
    @classmethod
    def check_accept_terms(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Please accept the Terms of Service and Privacy Policy to continue.")
        return value


# Sign in and verification codes (stories 1.1 and 1.2)


class SignInRequest(RequestBody):
    email: str = ""
    password: str = ""
    # Returned after a successful 2FA. Sending it back skips the code on this device.
    device_token: str | None = None
    # Which app is signing in: web sessions time out sooner (story 1.2). A trusted device keeps
    # the platform it had when it passed 2FA, and a browser always gets "web".
    platform: Platform = "web"

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value, "Email is required.")

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Password is required.")
        return value


class SignOutRequest(RequestBody):
    # Lets the app forget its device even when the session has already timed out.
    device_token: str | None = None


class VerifyRequest(RequestBody):
    challenge_id: uuid.UUID
    code: str = ""
    platform: Platform = "web"  # as in SignInRequest

    @field_validator("code")
    @classmethod
    def check_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please enter the verification code sent to your email.")
        return value


class ResendCodeRequest(RequestBody):
    challenge_id: uuid.UUID


class VerificationRequired(BaseModel):
    """The next screen is the Verification screen: a code was emailed."""

    status: Literal["verification_required"] = "verification_required"
    challenge_id: uuid.UUID
    purpose: Literal["verify_email", "sign_in"]
    expires_in_seconds: int
    # How long until "Resend code" works (stories 1.1 and 1.2: after 60 seconds), so the
    # app's countdown follows the server's setting.
    resend_after_seconds: int


class SignedIn(BaseModel):
    status: Literal["signed_in"] = "signed_in"
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    # Set after a successful 2FA: keep it on the device and send it with the next sign-in.
    device_token: str | None = None


# Passwords (stories 1.3 and 11.2)


class ForgotPasswordRequest(RequestBody):
    email: str = ""

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value, "Email is required.")


class ResetTokenRequest(RequestBody):
    token: str


class ResetPasswordRequest(RequestBody):
    token: str
    new_password: str = ""
    confirm_password: str = ""

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Please enter a new password.")
        if not meets_password_rules(value):
            raise ValueError(PASSWORD_RULES)
        return value

    @field_validator("confirm_password")
    @classmethod
    def check_confirm_password(cls, value: str, info: ValidationInfo) -> str:
        if not value or ("new_password" in info.data and value != info.data["new_password"]):
            raise ValueError(PASSWORDS_DONT_MATCH)
        return value


class ChangePasswordRequest(RequestBody):
    current_password: str = ""
    new_password: str = ""
    confirm_password: str = ""

    @field_validator("current_password")
    @classmethod
    def check_current_password(cls, value: str) -> str:
        if not value:
            raise ValueError(FIELD_REQUIRED)
        return value

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, value: str) -> str:
        if not value:
            raise ValueError(FIELD_REQUIRED)
        if not meets_password_rules(value):
            raise ValueError(PASSWORD_RULES)
        return value

    @field_validator("confirm_password")
    @classmethod
    def check_confirm_password(cls, value: str, info: ValidationInfo) -> str:
        if not value:
            raise ValueError(FIELD_REQUIRED)
        if "new_password" in info.data and value != info.data["new_password"]:
            raise ValueError("The passwords don’t match. Please try again.")
        return value
