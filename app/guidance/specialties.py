"""Story 3.4's appointment card: the specialty list, and checking what the client entered.

The list is `settings.provider_specialties`, so options can change without an app release.
"Other", with a write-in, always comes last. This module imports nothing from the
conversations package, so the conversations' widget rules can use it.
"""

from dataclasses import dataclass
from datetime import date

from app.core.ages import us_today, years_before
from app.core.config import ProviderSpecialty, settings
from app.core.errors import AppError
from app.core.schemas import clean_line, clean_name
from app.oracle.contract import APPOINTMENT_CARD, Widget

OTHER = "other"
OTHER_LABEL = "Other"
# Skip: "the notes are created without appointment details, for a primary care provider".
# Keep this code in settings.provider_specialties.
PRIMARY_CARE = "primary_care"

# Story 3.4's messages.
SPECIALTY_REQUIRED = "Please choose what kind of provider you’re seeing, so I can tailor the notes."
OTHER_REQUIRED = "Please tell me what kind of provider this is."
DATE_PASSED = (
    "That date has already passed. Would you like to choose a new date, or log this visit?"
)
UNCLEAR_SPECIALTY = (
    "Just to check, what kind of provider is {text}? For example, a GP, a specialist or a "
    "naturopath."
)
# Not in the stories (docs/decisions/phase-5-guidance-and-notes.md).
DATE_TOO_FAR = "Please choose a date within the next {years} years."


@dataclass(frozen=True)
class Appointment:
    """The appointment card, checked."""

    specialty: str  # a configured code, or OTHER
    specialty_other: str | None  # the write-in, with OTHER
    provider_name: str | None
    appointment_date: date | None
    # False for "Not yet" (the Oracle's suggestion) and Skip (primary care).
    booked: bool


def options() -> dict[str, ProviderSpecialty]:
    return {option.code: option for option in settings.provider_specialties}


def label(code: str, other: str | None) -> str:
    """What the notes, the title and the file name call the specialty."""
    if code == OTHER:
        return other or OTHER_LABEL
    option = options().get(code)
    # A code since removed from the settings still has notes saved with it.
    return option.label if option else code.replace("_", " ").capitalize()


def provider(code: str, other: str | None) -> str:
    """Who the client would see, with its article: "a cardiologist", "a naturopath"."""
    if code == OTHER:
        text = other or "provider"
        return f"{'an' if text[:1].lower() in 'aeiou' else 'a'} {text}"
    option = options().get(code)
    return option.provider if option else f"a {label(code, other).lower()} provider"


def _write_in(value: str | None, field: str) -> str | None:
    """A cleaned write-in (a specialty or a provider's name), or None when empty."""
    if value is None:
        return None
    try:
        return clean_name(value) or None
    except ValueError as error:  # longer than settings.name_max_length
        raise AppError(422, "too_long", str(error), field) from None


def check_date(appointment_date: date | None) -> None:
    """Not in the past, counted on Hawaii's date so no US client is refused today's date, and
    not years ahead."""
    if appointment_date is None:
        return
    if appointment_date < us_today():
        raise AppError(422, "appointment_date_passed", DATE_PASSED, "appointment_date")
    years = settings.appointment_max_years_ahead
    if years_before(appointment_date, years) > us_today():
        raise AppError(
            422, "appointment_date_too_far", DATE_TOO_FAR.format(years=years), "appointment_date"
        )


def read_appointment(
    *,
    specialty: str | None,
    specialty_other: str | None,
    provider_name: str | None,
    appointment_date: date | None,
    booking: str,
) -> Appointment:
    """Story 3.4's card rules. `booking` is how the client answered "Have you booked an
    appointment with a provider?": "booked" (the card, also for Scenario A), "not_yet" (the
    Oracle's suggested specialty) or "skip" (primary care, no details). Editing an appointment
    always counts as "booked"."""
    if booking == "skip":
        return Appointment(PRIMARY_CARE, None, None, None, booked=False)
    code = (specialty or "").strip()
    other = None
    if code == OTHER:
        other = _write_in(specialty_other, "specialty_other")
        if other is None:
            raise AppError(422, "specialty_other_required", OTHER_REQUIRED, "specialty_other")
    elif code not in options():
        if booking == "not_yet" and not code:
            code = PRIMARY_CARE  # the Oracle suggested nothing: start with primary care
        else:
            raise AppError(422, "specialty_required", SPECIALTY_REQUIRED, "specialty")
    if booking == "not_yet":
        return Appointment(code, other, None, None, booked=False)
    check_date(appointment_date)
    return Appointment(
        code,
        other,
        _write_in(provider_name, "provider_name"),
        appointment_date,
        booked=True,
    )


def _option_for(value: str) -> str | None:
    """The code a widget's specialty names, by code or label, ignoring case."""
    wanted = clean_line(value).casefold()
    for option in settings.provider_specialties:
        if wanted in (option.code.casefold(), option.label.casefold()):
            return option.code
    return None


def prepare_appointment_card(widget: Widget) -> Widget:
    """The appointment card widget as it's streamed and saved (app/conversations/widgets.py).
    Only its known fields are kept. A specialty that isn't on the list is filled in under
    "Other" (3.4, Scenario A), and a date that isn't a real ISO date is dropped."""
    card: Widget = {"kind": APPOINTMENT_CARD, "suggested": widget.get("suggested") is True}
    specialty, other = widget.get("specialty"), widget.get("specialty_other")
    if isinstance(specialty, str) and clean_line(specialty):
        code = _option_for(specialty)
        if code is not None:
            card["specialty"] = code
        else:
            write_in = other if specialty.strip() == OTHER and isinstance(other, str) else specialty
            write_in = clean_line(write_in)[: settings.name_max_length]
            if write_in:
                card["specialty"] = OTHER
                card["specialty_other"] = write_in
    name = widget.get("provider_name")
    if isinstance(name, str) and clean_line(name):
        card["provider_name"] = clean_line(name)[: settings.name_max_length]
    day = widget.get("appointment_date")
    if isinstance(day, str):
        try:
            card["appointment_date"] = date.fromisoformat(day).isoformat()
        except ValueError:
            pass
    return card
