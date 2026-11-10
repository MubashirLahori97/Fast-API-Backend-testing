"""The Wellness Plan (story 7.1) and the Wellness Protocols library."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.core.schemas import RequestBody


class LinkOut(BaseModel):
    """A link into the Wellness Protocols library: opens `tab` at `section`."""

    tab: str
    section: str
    title: str


class ProductOut(BaseModel):
    """A product link or a link to a test Deborah has supplied (adults only). Links only: never
    a price, discount, "buy now" or "Subscribe & Save"."""

    label: str
    url: str
    kind: str  # genesis_product | partner_product | medicine | test | other
    why: str | None = None
    # Genesis products: "How to take it (from the label): 2 pumps, twice daily." (7.1), the
    # label's directions word for word. Never a different dose.
    directions: str | None = None


class NoticeOut(BaseModel):
    """One of 7.1's safety notices, with the library link it mentions (the Gen-Pro® protocol
    for "How to take it (from the label): 2 pumps, twice daily. Here’s the Gen-Pro® protocol,
    too."), when that protocol is published."""

    code: str
    text: str
    link: LinkOut | None = None


class FocusAreaOut(BaseModel):
    id: uuid.UUID
    title: str  # e.g. "Sleep and night sweats"
    recommendations: list[str]
    time_frame: str | None  # e.g. "for 2 to 4 weeks"
    ask_prompt: str  # Ask the Oracle: the first message of a conversation about it
    added_at: datetime
    updated_at: datetime


class TodoOut(BaseModel):
    id: uuid.UUID
    number: int  # its place in the list, as in "item 6 in your plan"
    text: str
    done: bool
    completed_at: datetime | None
    protocol: LinkOut | None
    product: ProductOut | None
    follow_up_on: date | None  # when the Oracle checks in about it
    ask_prompt: str


class HealthyFourOut(BaseModel):
    name: str
    target: str


class PillarOut(BaseModel):
    """One of the Five Pillars, opened from the accordion: the personal adjustment and the
    library links (See the protocol)."""

    code: str  # nutraceuticals | diet | activity | sleep | mindset
    title: str
    adjustment: str | None
    links: list[LinkOut]
    healthy_four: list[HealthyFourOut] | None  # Diet: the DMAR® Healthy Four targets
    insulin_resistance_phase: str | None  # Diet
    # Diet without lean body mass: "Share your measurements with me, and I’ll work out your
    # personal targets."
    message: str | None


class ProgressOut(BaseModel):
    """The To Do list's progress, like a pill organiser: one dot per item, filled when done."""

    done: int
    total: int
    dots: list[bool]


class WellnessPlanOut(BaseModel):
    """The plan screen: always the latest version."""

    id: uuid.UUID
    profile_id: uuid.UUID
    title: str  # e.g. "Azka’s Wellness Plan"
    last_updated: datetime
    # The latest update's message ("I’ve started your Wellness Plan...", "Your Wellness Plan has
    # been updated.", or the focus-area-removed one), or "I couldn’t update your Wellness Plan
    # just now. I’ll try again shortly." while a failed update waits to be retried.
    message: str | None
    # Part 1, personal to the client.
    clinical_summary: str
    immediate_dietary_action: str | None  # the highlighted callout
    focus_areas: list[FocusAreaOut]  # newest at the top
    todos: list[TodoOut]
    progress: ProgressOut
    # "You’ve completed everything on your list. Well done!"
    all_done: str | None
    # Part 2, the Five Pillars (no Foundational Nutraceuticals for teens and children).
    pillars: list[PillarOut]
    products: list[ProductOut]  # adults only
    # 7.1's safety notices (hyperthyroidism, how to take Gen-Pro®, gender-affirming hormones, a
    # cleanse that isn't suitable) and flagged conflicts with a new prescription.
    notices: list[NoticeOut]
    alerts: list[str]
    # Shown within the plan whenever products appear: the product disclaimer and the one
    # disclosure box, 7.1's "Genesis Health Products, which makes Your Oracle, also makes and
    # sells Genesis Gold®, Sacred Seven® and Gen-Pro®".
    product_disclaimer: str | None
    disclosure: str | None


class WellnessPlanScreen(BaseModel):
    """`plan` is null before the profile's first guidance summary, with 7.1's "No plan yet"
    message."""

    plan: WellnessPlanOut | None
    message: str | None


class PlanCardOut(BaseModel):
    """The Wellness Plan card on the Home Dashboard and at the top of My Health."""

    profile_id: uuid.UUID
    title: str
    current_focus: str | None
    progress: ProgressOut
    # A check-in is due ("Check in with the Oracle · Due today · about 2 minutes").
    check_in_due: bool
    last_updated: datetime


class PlanCardScreen(BaseModel):
    card: PlanCardOut | None  # null: no plan yet, so the card isn't shown


class TickItem(RequestBody):
    """Tick a To Do item (done) or untick one ticked by mistake."""

    done: bool


class ItemTicked(BaseModel):
    item: TodoOut
    progress: ProgressOut
    all_done: str | None


class LibrarySectionOut(BaseModel):
    """A section with published knowledge base content (Super Admin 6.1): only those are
    listed, so an archived protocol disappears and an edit shows straight away."""

    key: str  # the link target
    title: str
    parts: list[str]  # what 7.1 says the section covers
    # The published text of the knowledge base's Protocol item for this section. Null when
    # the item is an uploaded file with no typed text.
    content: str | None = None
    updated_at: datetime | None = None  # when that version was published
    url: str | None  # an external guide (CALM's on Deborah's blog)


class LibraryTabOut(BaseModel):
    key: str
    title: str
    product: bool
    sections: list[LibrarySectionOut]
    # Product tabs: the FDA disclaimer, the ownership disclosure (7.1's disclosure sentence),
    # and only a Shop link to the Genesis Shopify store.
    fda_disclaimer: str | None
    ownership_disclosure: str | None
    shop_label: str | None
    shop_url: str | None


class LibraryOut(BaseModel):
    """The Wellness Protocols library as this profile sees it: teens and children get no
    product tabs, shop links or cleanse protocols. A tab with nothing published isn't listed."""

    tabs: list[LibraryTabOut]
