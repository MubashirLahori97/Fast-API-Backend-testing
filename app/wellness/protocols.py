"""The Wellness Protocols library (story 7.1): Deborah's protocols in one place, in four tabs.

Two parts:

- **The structure** (protocols.json in this package, or the file named by
  `settings.wellness_protocols_path`): the four tabs and their sections, in 7.1's order. Each
  section's `key` is its link target: the Five Pillars, the plan's To Do items, the guidance
  summary's "What You Can Do Now" and links in conversations all open "the right tab and
  section" by it.
- **The content** comes from the knowledge base (Super Admin 6.1: "It includes the Wellness
  Protocols shown to Clients"): each section shows the published knowledge base item of type
  Protocol whose title matches the section's title or one of its `titles` (ignoring case,
  ®/™, punctuation, "&" or "and", and a leading "The"). `load(db)` reads them per request, so
  a Super Admin's edit reaches clients straight away, and an archived protocol, or one not
  published yet, isn't shown: neither its section nor any link to it.

Links only: product tabs have one "Shop" link to the Genesis Shopify store's own page (nothing
about the client in it), and nothing anywhere has a price, discount, "buy now" or "Subscribe &
Save". Teens and children see no product tabs, shop links or cleanse protocols.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings

DEFAULT_PATH = Path(__file__).with_name("protocols.json")
KNOWLEDGE_TYPE = "protocol"  # knowledge_contents.content_type

# Placeholder until the attorney's text (not in the stories): each product tab's FDA
# disclaimer, also the plan's product disclaimer.
FDA_DISCLAIMER = (
    "These statements have not been evaluated by the Food and Drug Administration. This product "
    "is not intended to diagnose, treat, cure, or prevent any disease."
)
# Story 7.1's disclosure box, copied exactly (the story's text has no final full stop). The
# product tabs' "ownership disclosure" uses it too.
DISCLOSURE = (
    "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, "
    "Sacred Seven® and Gen-Pro®"
)
SHOP_LABEL = "Shop"
# Genesis products' basic directions from the label (3.3, 7.1), e.g. "How to take it (from the
# label): 4 g per 50 lb of body weight, daily."
HOW_TO_TAKE = "How to take it (from the label): {directions}."


def how_to_take(directions: str | None) -> str | None:
    """The label's directions, word for word, in the stories' sentence."""
    directions = (directions or "").strip().rstrip(".").strip()
    return HOW_TO_TAKE.format(directions=directions) if directions else None


# The Five Pillars, in 7.1's order, with the library sections each one links to. The Beet Test
# and the cleanses are never linked from a pillar: only from an item the Oracle recommends.
PILLARS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("nutraceuticals", "Foundational Nutraceuticals", ("genesis-gold",)),
    ("diet", "Diet", ("healthy-four", "insulin-resistance-diet")),
    ("activity", "Activity", ("hiit", "contraction-relaxation")),
    ("sleep", "Sleep", ("deep-sleep", "seven-secrets")),
    ("mindset", "Mindset", ("calm", "healing-meditation")),
)
# Foundational Nutraceuticals also links Sacred Seven® when it's recommended.
SACRED_SEVEN = "sacred-seven"
GEN_PRO = "gen-pro"
ADULT_ONLY_PILLARS = frozenset({"nutraceuticals"})


def normalize_title(title: str) -> str:
    """A title as it's matched: "Sleep: Deep Sleep & Longevity" and "sleep - deep sleep and
    longevity" are the same, and so are "Gen-Pro®", "Gen-Pro™" and "Gen Pro"."""
    # The marks go before NFKC, which would turn ™ into "TM".
    text = unicodedata.normalize("NFKC", re.sub(r"[®™©]", "", title)).casefold()
    text = text.replace("&", " and ")
    text = " ".join(re.sub(r"[^\w]+", " ", text).split())
    return text.removeprefix("the ")


@dataclass(frozen=True)
class Section:
    key: str  # the link target
    tab: str
    title: str
    parts: tuple[str, ...]  # what 7.1 says the section covers
    product: bool  # in a product tab: adults only
    cleanse: bool  # a cleanse or its Beet Test: adults only, and only when recommended
    external_url: str | None  # CALM's full guide on Deborah's blog
    match_titles: frozenset[str]  # normalized knowledge base titles this section shows


@dataclass(frozen=True)
class Tab:
    key: str
    title: str
    product: bool
    sections: tuple[Section, ...]

    @property
    def shop_url(self) -> str | None:
        return settings.wellness_shop_links.get(self.key) if self.product else None


EXTERNAL_LINKS = {"calm_guide": lambda: settings.calm_guide_url}


def _load(path: Path) -> tuple[Tab, ...]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    tabs = []
    for tab in data["tabs"]:
        product = bool(tab.get("product"))
        sections = tuple(
            Section(
                key=section["key"],
                tab=tab["key"],
                title=section["title"],
                parts=tuple(section.get("parts") or ()),
                product=product,
                cleanse=bool(section.get("cleanse")),
                external_url=EXTERNAL_LINKS[section["external"]]()
                if section.get("external")
                else None,
                match_titles=frozenset(
                    normalize_title(title)
                    for title in [section["title"], *(section.get("titles") or [])]
                ),
            )
            for section in tab["sections"]
        )
        tabs.append(Tab(key=tab["key"], title=tab["title"], product=product, sections=sections))
    keys = [section.key for tab in tabs for section in tab.sections]
    if len(keys) != len(set(keys)):
        raise ValueError("The Wellness Protocols library has two sections with the same key.")
    titles = [title for tab in tabs for section in tab.sections for title in section.match_titles]
    if len(titles) != len(set(titles)):
        raise ValueError("Two Wellness Protocols sections match the same knowledge base title.")
    linked = {key for _, _, links in PILLARS for key in links} | {SACRED_SEVEN, GEN_PRO}
    missing = linked - set(keys)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"The Wellness Protocols links point to missing sections: {names}")
    return tuple(tabs)


TABS = _load(
    Path(settings.wellness_protocols_path) if settings.wellness_protocols_path else DEFAULT_PATH
)
SECTIONS = {section.key: section for tab in TABS for section in tab.sections}


def known(key: str | None) -> bool:
    """Whether the key is one of the library's sections (published or not)."""
    return bool(key) and key in SECTIONS


def suitable(key: str | None, *, adult: bool) -> bool:
    """Whether a link to this section may be kept for this age: any section for adults; for
    teens and children, none of the product tabs or cleanses (7.1). Says nothing about whether
    the protocol is published now: that's checked when it's shown (`Library`)."""
    found = SECTIONS.get(key) if key else None
    return found is not None and (adult or not (found.product or found.cleanse))


@dataclass(frozen=True)
class Published:
    """A section's knowledge base content: the item's published version."""

    content_id: str
    version: int
    text: str | None  # null when the item is an uploaded file only
    published_at: datetime | None


@dataclass(frozen=True)
class Library:
    """The library as it is now: the structure, with the published knowledge base content of
    each section. Sections without published content aren't shown, and links to them are
    dropped."""

    content: dict[str, Published]  # by section key

    def section(self, key: str | None) -> Section | None:
        return SECTIONS[key] if key and key in self.content else None

    def allowed(self, key: str | None, *, adult: bool) -> bool:
        return self.section(key) is not None and suitable(key, adult=adult)

    def link(self, key: str | None, *, adult: bool) -> Section | None:
        return self.section(key) if self.allowed(key, adult=adult) else None

    def tabs_for(self, adult: bool) -> list[Tab]:
        """The library as this profile sees it (7.1's "Teens and Children": no product tabs,
        shop links or cleanse protocols). A tab with nothing published isn't shown."""
        tabs = []
        for tab in TABS:
            if tab.product and not adult:
                continue
            sections = tuple(s for s in tab.sections if self.allowed(s.key, adult=adult))
            if sections:
                tabs.append(
                    Tab(key=tab.key, title=tab.title, product=tab.product, sections=sections)
                )
        return tabs


def load(db: Session) -> Library:
    """Reads the published Wellness Protocols from the knowledge base (one query). Where two
    published items match one section, the most recently published is shown."""
    from app.knowledge.service import published_contents  # imported here: no import cycle

    content: dict[str, Published] = {}
    for item, version in published_contents(db, KNOWLEDGE_TYPE):
        title = normalize_title(version.title)
        section = next((s for s in SECTIONS.values() if title in s.match_titles), None)
        if section is None:
            continue  # a protocol that isn't one of the library's sections
        published = Published(
            content_id=str(item.id),
            version=version.number,
            text=version.text,
            published_at=version.published_at,
        )
        earlier = content.get(section.key)
        if earlier is None or _when(published) > _when(earlier):
            content[section.key] = published
    return Library(content=content)


def _when(published: Published) -> datetime:
    return published.published_at or datetime.min.replace(tzinfo=UTC)
