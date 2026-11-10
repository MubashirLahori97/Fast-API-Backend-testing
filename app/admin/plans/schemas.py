"""Subscription & Billing management (Super Admin stories 8.1 and 8.2). Prices are whole US
cents, like the rest of billing; the admin panel shows `display`."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationInfo, field_validator

from app.billing.catalog import PlanStatus, PlanType
from app.billing.schemas import Price
from app.core.config import settings
from app.core.schemas import RequestBody, clean_line

# Super Admin 8.1 and 8.2's messages.
PRICE_INVALID = "Please enter a valid price."
TRIAL_INVALID = "Please enter a trial length in days, for example 14."
MEMBERS_INVALID = "Please enter how many family members are included."
NAME_EMPTY = "Please enter a plan name."
TYPE_EMPTY = "Please choose a plan type."
MONTHLY_PRICE_INVALID = "Please enter a valid monthly price."
FAMILY_FIELDS_EMPTY = "Please enter the family members included and the add-on price."
FEATURES_EMPTY = "Please add at least one feature."


def whole_number(value: object, low: int, high: int, message: str) -> int:
    """A whole number from `low` to `high` (an int, or a string of digits), else `message`."""
    if isinstance(value, bool):
        raise ValueError(message)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(message)
    return value


def _cents(value: object, message: str) -> int:
    return whole_number(value, 1, settings.plan_max_price_cents, message)


def _features(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(FEATURES_EMPTY)
    features = [clean_line(item) for item in value if isinstance(item, str)]
    features = [feature for feature in features if feature]
    if not features:
        raise ValueError(FEATURES_EMPTY)
    if len(features) > settings.plan_max_features:
        raise ValueError(f"Please keep it to {settings.plan_max_features} features or fewer.")
    if any(len(feature) > settings.plan_feature_max_length for feature in features):
        raise ValueError(
            f"Please keep each feature to {settings.plan_feature_max_length} characters or fewer."
        )
    return features


def _name(value: object) -> object:
    if value is None:
        value = ""
    if not isinstance(value, str):
        return value
    value = clean_line(value)
    if not value:
        raise ValueError(NAME_EMPTY)
    if len(value) > settings.name_max_length:
        raise ValueError(f"Please keep the name to {settings.name_max_length} characters or fewer.")
    return value


class PlanEdit(RequestBody):
    """8.1's Edit. Only the fields sent change:

    - Free trial: `trial_days`;
    - Individual: `monthly_price_cents`, `features`, `status`;
    - Family: those, plus `family_members_included` and `add_on_price_cents`;
    - a draft: also `name`.

    A price change, or making a plan inactive, needs `confirmed: true` (409 with the story's
    confirmation otherwise)."""

    name: str | None = None
    monthly_price_cents: int | None = None
    add_on_price_cents: int | None = None
    family_members_included: int | None = None
    trial_days: int | None = None
    features: list[str] | None = None
    status: Literal["active", "inactive"] | None = None
    confirmed: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def check_name(cls, value: object) -> object:
        return None if value is None else _name(value)

    @field_validator("monthly_price_cents", "add_on_price_cents", mode="before")
    @classmethod
    def check_price(cls, value: object) -> object:
        return None if value is None else _cents(value, PRICE_INVALID)

    @field_validator("family_members_included", mode="before")
    @classmethod
    def check_members(cls, value: object) -> object:
        if value is None:
            return None
        return whole_number(value, 1, settings.plan_max_family_members, MEMBERS_INVALID)

    @field_validator("trial_days", mode="before")
    @classmethod
    def check_trial(cls, value: object) -> object:
        if value is None:
            return None
        return whole_number(value, 1, settings.plan_max_trial_days, TRIAL_INVALID)

    @field_validator("features", mode="before")
    @classmethod
    def check_features(cls, value: object) -> object:
        return None if value is None else _features(value)


class PlanNew(RequestBody):
    """8.2's + Add plan. There's only one Free trial, so the type is Individual or Family."""

    name: str = ""
    plan_type: Literal["individual", "family"] | None = None
    monthly_price_cents: int | None = None
    family_members_included: int | None = None
    add_on_price_cents: int | None = None
    features: list[str] = []
    action: Literal["draft", "publish"] = "draft"
    confirmed: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def check_name(cls, value: object) -> object:
        return _name(value)

    @field_validator("plan_type", mode="before")
    @classmethod
    def check_type(cls, value: object) -> object:
        if value not in ("individual", "family"):
            raise ValueError(TYPE_EMPTY)
        return value

    @field_validator("monthly_price_cents", mode="before")
    @classmethod
    def check_price(cls, value: object) -> object:
        if value is None:
            raise ValueError(MONTHLY_PRICE_INVALID)
        return _cents(value, MONTHLY_PRICE_INVALID)

    @field_validator("family_members_included", "add_on_price_cents", mode="before")
    @classmethod
    def check_family(cls, value: object, info: ValidationInfo) -> object:
        if info.data.get("plan_type") != "family":
            return None  # only the Family plan has them
        if info.field_name == "add_on_price_cents" and "family_members_included" not in info.data:
            return None  # one message for both fields, already given
        try:
            if info.field_name == "family_members_included":
                return whole_number(value, 1, settings.plan_max_family_members, "")
            return _cents(value, "")
        except ValueError:
            raise ValueError(FAMILY_FIELDS_EMPTY) from None

    @field_validator("features", mode="before")
    @classmethod
    def check_features(cls, value: object) -> object:
        return _features(value)


class PublishBody(RequestBody):
    confirmed: bool = False


class PersonRef(BaseModel):
    id: uuid.UUID
    first_name: str | None


class PlanRow(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    plan_type: PlanType
    status: PlanStatus
    monthly_price: Price | None  # paid plans
    trial_days: int | None  # the Free trial
    family_members_included: int | None  # the Family plan
    add_on_price: Price | None  # the Family plan, per add-on member
    clients: int  # Clients on the plan now


class PlanList(BaseModel):
    items: list[PlanRow]


class PriceChangeOut(BaseModel):
    monthly_price: Price | None
    add_on_price: Price | None
    trial_days: int | None
    family_members_included: int | None
    changed_by: PersonRef | None
    changed_at: datetime


class PlanDetail(PlanRow):
    features: list[str]
    price_history: list[PriceChangeOut]  # newest first
    published_at: datetime | None
    created_at: datetime
    # "Make this plan inactive? ...", for the Set inactive button.
    set_inactive_confirmation: str | None


class PlanSaved(BaseModel):
    plan: PlanDetail
    message: str
