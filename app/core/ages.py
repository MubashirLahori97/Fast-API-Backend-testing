"""Ages, worked out from a date of birth the same way everywhere."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from app.core.config import settings

# Hawaii is the last US state to reach each new date, and it has no daylight saving time.
HAWAII = timezone(timedelta(hours=-10))

# Story 3.1's age groups, which route the Oracle's questions. A teen is 13 up to the age of
# majority (13 to 17 while it's 18 everywhere, docs/PLAN.md question 22).
AgeGroup = Literal["under_13", "teen", "adult", "60_plus"]
TEEN_FROM_AGE = 13
OLDER_ADULT_FROM_AGE = 60


def today() -> date:
    """ "Today" for most age rules is the UTC date: within a day of the client's own date."""
    return datetime.now(UTC).date()


def us_today() -> date:
    """The date in Hawaii. A birthday counts once it has started everywhere in the US, so
    nobody is treated as older than they are where they live."""
    return datetime.now(HAWAII).date()


def years_before(day: date, years: int) -> date:
    """The same calendar date `years` earlier; 29 February becomes 28 February."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def age_on(date_of_birth: date, on: date) -> int:
    birthday_passed = (on.month, on.day) >= (date_of_birth.month, date_of_birth.day)
    return on.year - date_of_birth.year - (0 if birthday_passed else 1)


def is_adult(date_of_birth: date) -> bool:
    """Reached the age of majority (story 1.1): old enough for an account of their own."""
    return age_on(date_of_birth, us_today()) >= settings.age_of_majority


def age_group(date_of_birth: date) -> AgeGroup:
    """The profile's age group (story 3.1): under 13, teen, adult (to 59), or 60 and over.
    Counted on Hawaii's date like is_adult, so "teen" ends exactly where is_adult starts."""
    age = age_on(date_of_birth, us_today())
    if age < TEEN_FROM_AGE:
        return "under_13"
    if age < settings.age_of_majority:
        return "teen"
    if age < OLDER_ADULT_FROM_AGE:
        return "adult"
    return "60_plus"
