"""The widget kinds the backend enforces in the Oracle's replies (story 3.1). Each reply's
widgets pass through `prepare_widget` as they stream, and `closing_widgets` adds what goes at
the end, so what's saved is exactly what was streamed. Other kinds pass through unchanged.

Health details (story 3.1's health_fact widget) are the exception: `prepare_widget` only checks
their shape, and the service saves each one straight to the health profile with the reply
(app/conversations/service.py). They're never streamed or kept in the reply: since the 6 Nov
19:22 stories nothing is confirmed in the chat, and 3.3 lists them below the summary.

The kinds are described in app/oracle/contract.py.
"""

from typing import Any, get_args
from urllib.parse import urlsplit

from app.core.schemas import clean_line
from app.guidance.specialties import prepare_appointment_card
from app.oracle.contract import (
    APPOINTMENT_CARD,
    CONSULT_SUPPORT,
    DISCLOSURE,
    GENESIS_PRODUCTS,
    HEALTH_FACT,
    LABEL_DIRECTIONS,
    MEDICINE_LINK,
    PRIVACY_NOTICE,
    PRODUCT_LINK,
    PROVIDER_NOTES,
    SUPPORT_OFFER,
    SUPPORT_REQUEST_SENT,
    TEST_LINK,
    ProductType,
    SupportRequestKind,
    Widget,
)

# Placeholder text until the attorney's final wording is in (story 6.1 lists what the privacy
# notice says). Not in the stories.
PRIVACY_NOTICE_TEXT = (
    "These questions are optional, and you can skip any of them. The answers are used only to "
    "tailor your health education, are never sold or shared with advertisers, are encrypted, "
    "and can be edited or deleted at any time."
)
# Story 3.1's disclosure box (also 3.3's and 7.1's), word for word.
DISCLOSURE_TEXT = (
    "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, "
    "Sacred Seven® and Gen-Pro®."
)
# Story 3.1's label directions; [directions] come word for word from the knowledge base.
LABEL_DIRECTIONS_TEXT = "How to take it (from the label): {directions}."
CONSULT_SUPPORT_LABEL = "Consult with support team"  # stories 3.1 and 10.1
LINK_LABEL_MAX_LENGTH = 100
LINK_URL_MAX_LENGTH = 2000
LABEL_DIRECTIONS_MAX_LENGTH = 300
QUESTION_KEY_MAX_LENGTH = 100  # question codes in app/health/questions.json are much shorter
SUPPORT_REQUEST_KINDS = frozenset(get_args(SupportRequestKind))
PRODUCT_TYPES = frozenset(get_args(ProductType))
# Story 3.1: the Oracle links to Drugs.com for medicine information.
MEDICINE_LINK_HOSTS = ("drugs.com",)


def prepare_widget(
    widget: Widget, *, adult: bool, teen_account: bool = False, offer_support: bool = True
) -> Widget | None:
    """The widget as it's streamed and saved, or None to drop it.

    - Product links, test links and label directions are for adults only (story 3.1's
      "Products and links (adults only)"): dropped for anyone under the age of majority. Links
      are dropped without a label or an https URL; medicine links (every age) unless they're
      on Drugs.com; label directions unless they name a Genesis product and give directions.
    - Disclosure boxes from the Oracle are dropped: `closing_widgets` adds the one box.
    - The privacy notice and the consult card get the backend's text, whatever the reply said.
      A teen with their own account (`teen_account`) doesn't see the consult card (story 10.1).
    - Support offers (story 10.1) keep only their kind, and are dropped when `offer_support`
      is false: the message answered wasn't found safe, so it gets the safety path (3.2).
    - Health details keep only their question and value, for the service to save.
    - The backend's own cards (provider notes, support request sent) are never the Oracle's."""
    kind = widget.get("kind")
    if kind == PRODUCT_LINK:
        return _product_link(widget) if adult else None
    if kind == TEST_LINK:
        return _test_link(widget) if adult else None
    if kind == MEDICINE_LINK:
        return _medicine_link(widget)
    if kind == LABEL_DIRECTIONS:
        return _label_directions(widget) if adult else None
    if kind in (DISCLOSURE, PROVIDER_NOTES, SUPPORT_REQUEST_SENT):
        return None
    if kind == PRIVACY_NOTICE:
        return {"kind": PRIVACY_NOTICE, "text": PRIVACY_NOTICE_TEXT}
    if kind == CONSULT_SUPPORT:
        return None if teen_account else {"kind": CONSULT_SUPPORT, "label": CONSULT_SUPPORT_LABEL}
    if kind == SUPPORT_OFFER:
        request_kind = widget.get("request_kind")
        if not offer_support or request_kind not in SUPPORT_REQUEST_KINDS:
            return None
        return {"kind": SUPPORT_OFFER, "request_kind": request_kind}
    if kind == HEALTH_FACT:
        return _health_fact(widget)
    # Phase 5 (app/guidance/): the appointment card keeps only its known fields, with a
    # specialty off the list moved to "Other" (story 3.4).
    if kind == APPOINTMENT_CARD:
        return prepare_appointment_card(widget)
    return widget


def _link(widget: Widget) -> tuple[str, str] | None:
    """The label and URL, when the label isn't empty and the URL is https, with no spaces or
    hidden characters."""
    label, url = widget.get("label"), widget.get("url")
    if not isinstance(label, str) or not isinstance(url, str):
        return None
    label = clean_line(label)[:LINK_LABEL_MAX_LENGTH]
    if not label or len(url) > LINK_URL_MAX_LENGTH or url != clean_line(url):
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        return None
    return label, url


def _product_link(widget: Widget) -> Widget | None:
    """`product_type` says whether the reply needs the disclosure box: a Genesis product or an
    affiliate link does. A missing or unknown type is taken as "affiliate", so a product link
    is never shown without the box by mistake."""
    link = _link(widget)
    if link is None:
        return None
    product_type = widget.get("product_type")
    if product_type not in PRODUCT_TYPES:
        product_type = "affiliate"
    return {"kind": PRODUCT_LINK, "label": link[0], "url": link[1], "product_type": product_type}


def _test_link(widget: Widget) -> Widget | None:
    """A link to a test Deborah supplied (3.1: no test ordering in the app). An affiliate one
    (`affiliate` true) adds the disclosure box."""
    link = _link(widget)
    if link is None:
        return None
    affiliate = widget.get("affiliate") is True
    return {"kind": TEST_LINK, "label": link[0], "url": link[1], "affiliate": affiliate}


def _medicine_link(widget: Widget) -> Widget | None:
    """A medicine's page on Drugs.com (3.1). Any other site is dropped."""
    link = _link(widget)
    if link is None:
        return None
    host = (urlsplit(link[1]).hostname or "").lower()
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in MEDICINE_LINK_HOSTS):
        return None
    return {"kind": MEDICINE_LINK, "label": link[0], "url": link[1]}


def _label_directions(widget: Widget) -> Widget | None:
    """Story 3.1's "How to take it (from the label): [directions]." for Genesis Gold®, Sacred
    Seven® or Gen-Pro®. The backend writes the sentence; the directions are the knowledge
    base's, word for word (the Oracle's job: the backend has no copy of the labels)."""
    product, directions = widget.get("product"), widget.get("directions")
    if product not in GENESIS_PRODUCTS or not isinstance(directions, str):
        return None
    directions = clean_line(directions).rstrip(".")
    if not directions or len(directions) > LABEL_DIRECTIONS_MAX_LENGTH:
        return None
    return {
        "kind": LABEL_DIRECTIONS,
        "product": product,
        "product_name": GENESIS_PRODUCTS[product],
        "directions": directions,
        "text": LABEL_DIRECTIONS_TEXT.format(directions=directions),
    }


def _health_fact(widget: Widget) -> Widget | None:
    """The detail's shape only. Whether it fits the profile is
    app.health.service.save_from_conversation's check, which treats the value as untrusted,
    like the app's."""
    question_key, other = widget.get("question_key"), widget.get("other")
    if not isinstance(question_key, str) or not 0 < len(question_key) <= QUESTION_KEY_MAX_LENGTH:
        return None
    if other is not None and not isinstance(other, str):
        return None
    return {
        "kind": HEALTH_FACT,
        "question_key": question_key,
        "value": widget.get("value"),
        "other": other,
    }


def support_request_sent(request_id: Any, request_kind: str, offer_message_id: Any) -> Widget:
    """On the backend's line confirming a request from the conversation (story 10.1)."""
    return {
        "kind": SUPPORT_REQUEST_SENT,
        "support_request_id": str(request_id),
        "request_kind": request_kind,
        "offer_message_id": str(offer_message_id),
    }


def needs_disclosure(widget: Widget) -> bool:
    """Story 3.1: the box is shown "When Genesis products/affiliate links are recommended". A
    test link that isn't an affiliate link, a medicine link and an "other" product don't need
    it."""
    kind = widget.get("kind")
    if kind == PRODUCT_LINK:
        return widget.get("product_type") in ("genesis", "affiliate")
    if kind == TEST_LINK:
        return widget.get("affiliate") is True
    return kind == LABEL_DIRECTIONS  # a Genesis product recommendation


def closing_widgets(widgets: list[Widget]) -> list[Widget]:
    """One disclosure box at the end of a reply that recommends a Genesis product or has an
    affiliate link (story 3.1), with the story's ownership sentence."""
    if any(needs_disclosure(widget) for widget in widgets):
        return [{"kind": DISCLOSURE, "text": DISCLOSURE_TEXT}]
    return []
