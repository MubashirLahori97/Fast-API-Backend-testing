"""The Home Dashboard's response (story 4.1).

Every widget is in the list, in the story's order, whether it's shown or not. Each one says:

- `shown`: draw it. Hidden widgets carry no data.
- `locked`: draw it greyed out; tapping it shows `locked_message` (the upgrade prompt). Locked
  widgets carry no records (no conversation, plan, notes or steps), only what's needed to draw
  the card.
- `title`: the card's heading, with the family member's name when theirs is active.

Each widget carries only ids, titles, dates and counts: the screen it opens loads the rest.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.profiles.options import FamilyRelationship
from app.profiles.schemas import ProfileOut
from app.teens.schemas import TeenLinkStatus
from app.wellness.schemas import PlanCardOut


class TopBar(BaseModel):
    # "Good morning, Sarah" for the client's own profile (a teen's too), "Here’s Azka’s space"
    # for a family member.
    greeting: str
    unread_notifications: int  # the bell's count (12.1)
    # The profile icon (4.2): the active profile's initial, which opens the profile panel.
    profile_initial: str
    profile_first_name: str


class TrialBanner(BaseModel):
    """Story 4.1's free trial banner, with a Choose a plan button (9.1's plans screen)."""

    days_left: int
    message: str  # "[X] days left in your free trial."


class UpgradePrompt(BaseModel):
    """The trial (or a subscription) has ended: the dashboard shows the upgrade prompt, and
    every widget is locked. The codes are the ones the message box refuses with."""

    code: Literal["trial_ended", "subscription_ended"]
    message: str


class _Widget(BaseModel):
    shown: bool
    locked: bool
    title: str
    locked_message: str | None  # shown when a locked widget is tapped


class ConversationWidget(_Widget):
    """Continue your conversation, or Ask the Oracle when there's none yet (always shown)."""

    code: Literal["conversation"] = "conversation"
    mode: Literal["continue", "ask"]
    # The last conversation: GET /conversations/{conversation_id}. With `safety_hold`, it's
    # paused by an emergency or crisis (3.2) and opens on the hold's options.
    conversation_id: uuid.UUID | None
    topic: str | None  # null until the Oracle's first reply
    last_message_at: datetime | None
    safety_hold: bool
    placeholder: str | None  # "Ask me anything", for Ask the Oracle


class WellnessPlanWidget(_Widget):
    """Shown once the profile has a Wellness Plan; greyed out during the trial (7.1). View
    plan opens GET /profiles/{profile_id}/wellness-plan."""

    code: Literal["wellness_plan"] = "wellness_plan"
    card: PlanCardOut | None  # the current focus and the progress dots


class CompleteHealthProfileWidget(_Widget):
    """Shown until the health profile is complete. Complete now opens My Health's form."""

    code: Literal["complete_health_profile"] = "complete_health_profile"
    completion: int | None  # the percentage


class UpdateHealthProfileWidget(_Widget):
    """Shown 3, 6 and 12 months after the health profile's last update, and after a logged
    provider visit, until the profile is updated again."""

    code: Literal["update_health_profile"] = "update_health_profile"
    reason: Literal["months", "visit_logged"] | None
    months: int | None  # 3, 6 or 12, with reason "months"
    message: str | None  # "It’s been 6 months since we last updated your profile. ..."


class NextStep(BaseModel):
    """One suggestion in What's next, and the record it opens:

    - appointment: an upcoming appointment with notes ready, GET /provider-notes/{id};
    - log_visit: a past appointment not logged yet, Log visit on those notes (5.2);
    - plan_check_in: a Wellness Plan item due for a check-in (7.1)."""

    kind: Literal["appointment", "log_visit", "plan_check_in"]
    text: str
    provider_note_id: uuid.UUID | None
    appointment_date: date | None
    wellness_item_id: uuid.UUID | None


class WhatsNextWidget(_Widget):
    """One or two suggested next steps; shown when there are any (greyed out on the trial)."""

    code: Literal["whats_next"] = "whats_next"
    steps: list[NextStep]


class VisitNotesWidget(_Widget):
    """Quick access to My Visit Notes (5.1). Always shown."""

    code: Literal["visit_notes"] = "visit_notes"
    notes_count: int | None  # summaries, notes and logged visits
    upcoming_count: int | None  # upcoming appointments


class MyHealthWidget(_Widget):
    """Quick access to My Health (6.1). Always shown."""

    code: Literal["my_health"] = "my_health"
    completion: int | None
    # What the Oracle picked up in conversations, waiting to be confirmed or dismissed
    # (GET /profiles/{profile_id}/health-facts).
    pending_facts: int | None


class InvitedTeenCard(BaseModel):
    """An invited teen with their own account, as the parent entered them, and the status.
    Never anything of the teen's own."""

    id: uuid.UUID  # the teen link, for Manage Family's /teen-links/{id} actions
    first_name: str
    relationship: FamilyRelationship
    status: TeenLinkStatus  # invite_sent, joined, turned_off or access_paused


class MyFamilyWidget(_Widget):
    """The Family plan's family profiles and invited teens, with Add family member. On the
    trial or the Individual plan it's locked: the Family plan's upgrade prompt. Hidden while a
    family member's profile is active, and on a teen's own account."""

    code: Literal["my_family"] = "my_family"
    members: list[ProfileOut]  # finished family members, as in the profile panel
    invited_teens: list[InvitedTeenCard]
    places_used: int | None
    places_included: int | None
    # A place is free. When it isn't, Add family member offers the paid add-on (4.2, 9.1).
    can_add: bool


class ConsultWidget(_Widget):
    """Consult with support team: opens 10.1's consultation form (POST
    /profiles/{profile_id}/support-requests with kind "consultation"). Not on a teen's own
    account."""

    code: Literal["consult_support"] = "consult_support"


Widget = Annotated[
    ConversationWidget
    | WellnessPlanWidget
    | CompleteHealthProfileWidget
    | UpdateHealthProfileWidget
    | WhatsNextWidget
    | VisitNotesWidget
    | MyHealthWidget
    | MyFamilyWidget
    | ConsultWidget,
    Field(discriminator="code"),
]


class HomeDashboardOut(BaseModel):
    """The active profile's Home Dashboard. `widgets` are in the story's order."""

    profile_id: uuid.UUID
    is_self: bool
    # A teen with their own account (1.5): no My Family, plans, billing or trial banner.
    teen_account: bool
    # The active profile is below the age of majority (a teen's own account, or a managed teen
    # or child): education only, with no product promotion anywhere on the dashboard.
    education_only: bool
    top_bar: TopBar
    trial_banner: TrialBanner | None
    upgrade_prompt: UpgradePrompt | None
    widgets: list[Widget]
