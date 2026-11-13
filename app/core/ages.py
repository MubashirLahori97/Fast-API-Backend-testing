"""Ages, worked out from a date of birth the same way everywhere."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from app.core.config import settings

# Hawaii is the last US state to reach each new date, and it has no daylight saving time.
HAWAII = timezone(timedelta(hours=-10))

# Story 3.1's age groups, which route the Oracle's questions. A teen is 13 up to the age of
# majority in the state that counts (18, 19 or 21: see age_of_majority).
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


def age_of_majority(state: str | None) -> int:
    """The age of majority in a US state (stories 1.1, 3.1, 11.1): 19 in Alabama and Nebraska,
    21 in Mississippi, 18 everywhere else (settings.age_of_majority_by_state). An unknown or
    missing state gets the default, 18 (docs/decisions/state-age-of-majority.md).

    Whose state counts: the account's own state for its own profile and for a teen with their
    own account; the account holder's state for a family member (an assumption)."""
    if not state:
        return settings.age_of_majority
    return settings.age_of_majority_by_state.get(state.upper(), settings.age_of_majority)


def is_adult(date_of_birth: date, state: str | None) -> bool:
    """Reached the state's age of majority (story 1.1): old enough for an account of their own."""
    return age_on(date_of_birth, us_today()) >= age_of_majority(state)


def adult_on(date_of_birth: date, state: str | None) -> date:
    """The day the state's age of majority is reached, the same way age_on counts it: someone
    born on 29 February comes of age on 1 March in a year without one (docs/PLAN.md, question
    39)."""
    year = date_of_birth.year + age_of_majority(state)
    try:
        return date_of_birth.replace(year=year)
    except ValueError:
        return date(year, 3, 1)


def age_group(date_of_birth: date, state: str | None) -> AgeGroup:
    """The profile's age group (story 3.1): under 13, teen (to the state's age of majority),
    adult (to 59), or 60 and over. Counted on Hawaii's date like is_adult, so "teen" ends
    exactly where is_adult starts."""
    age = age_on(date_of_birth, us_today())
    if age < TEEN_FROM_AGE:
        return "under_13"
    if age < age_of_majority(state):
        return "teen"
    if age < OLDER_ADULT_FROM_AGE:
        return "adult"
    return "60_plus"
