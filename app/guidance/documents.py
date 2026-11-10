"""How summaries and notes are laid out: the stories' fixed texts, the sections in order, and
the plain text (Copy text) and PDF (Download, Print) versions.

The screen, the copied text and the PDF are all built from the same `Document`, so each one has
the same sections, the disclaimer and, when relevant, the one disclosure box (stories 3.3 and
3.5). PDFs are made on request and never stored (3.5).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote

from fpdf import FPDF, XPos, YPos

from app.guidance.schemas import Paper, SectionItemOut, SectionOut
from app.wellness.protocols import how_to_take

# Story 3.3's texts.
SUMMARY_DISCLOSURE = (
    "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, "
    "Sacred Seven® and Gen-Pro®."
)
ADDED_TO_HEALTH_PROFILE = (
    "Here’s what I’ve added to your health profile from our conversation. If anything isn’t "
    "right, you can change or remove it in My Health."
)
SUMMARY_INTRODUCTION = "Thank you for sharing all of that. Here’s what I’m seeing."
PRODUCT_NOTE = (
    "Genesis Gold® contains no hormones. Please let your provider know if you start it "
    "alongside any medication."
)
SUMMARY_DISCLAIMER = (
    "This is educational guidance from the Oracle, an AI system. It isn’t a diagnosis or "
    "prescription."
)
SUMMARY_TITLES = {
    "what_im_hearing": "What I’m Hearing",
    "hypothalamic_connection": "Hypothalamic Connection",
    "what_this_may_mean": "What This May Mean",
    "questions_for_provider": "Questions for Your Provider",
    "tests_worth_discussing": "Tests Worth Discussing",
    "what_you_can_do_now": "What You Can Do Now",
    "recommendations": "Recommendations",
    "recommended_next_steps": "Recommended Next Steps",
    "still_needed": "What I’d Still Like to Know",  # First Look only; not in the stories
    "word_from_the_oracle": "A Word from the Oracle",
}

# Story 3.4's texts.
WHAT_THIS_IS = (
    "A summary prepared by Your Oracle based on my symptoms, history and our conversation. I am "
    "bringing this to help my provider understand the full picture."
)
# Copied exactly from the 6 Nov 19:22 story, including the missing space after "hormones."
GENESIS_GOLD_NOTE = (
    "Genesis Gold® is a nutraceutical formulation designed to support hypothalamic function. "
    "It contains no hormones.I would like your awareness as I begin a trial of at least 90 days."
)
NO_RED_FLAGS = "No urgent red flags identified in this session."
# 3.4 and 3.5's disclaimer and 3.4's disclosure box, copied exactly (neither has a final full
# stop in the stories).
NOTES_DISCLAIMER = (
    "This document was prepared by Your Oracle, an AI health education tool developed by "
    "Genesis Health Products Inc. It is not a diagnosis, a prescription, or a substitute for "
    "professional medical care"
)
NOTES_DISCLOSURE = (
    "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, "
    "Sacred Seven® and Gen-Pro®"
)
NOTES_TITLES = {
    "chief_complaint": "1. Chief complaint",
    "clinical_context": "2. Clinical context",
    "labs_requested": "3. Labs I am requesting",
    "questions": "4. Questions for my provider",
    "medications": "5. Current medications and supplements",
    "red_flags": "Red flags screened by the Oracle",
    "recommendation": "The Oracle’s recommendation to me",
}

# Not in the stories (docs/decisions/phase-5-guidance-and-notes.md).
FIRST_LOOK_INTRODUCTION = "Here’s what I can say so far, from what you’ve shared."
WHAT_THIS_IS_TITLE = "What this is"
REPORTED_LABS = "Lab values as I reported them"
ALSO_REQUEST = "Also request"
DISCLOSURE_TITLE = "Disclosure"

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PREVIEW_LENGTH = 120


def show_date(day: date) -> str:
    """12 Nov 2026, the same in every locale."""
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def file_date(day: date) -> str:
    """12-Nov-2026, as in 3.5's "Notes_Sarah_Cardiology_12-Nov-2026.pdf"."""
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


def preview(text: str) -> str:
    """The first line of a section, shortened for a card."""
    line = " ".join(text.split())
    return line if len(line) <= PREVIEW_LENGTH else line[: PREVIEW_LENGTH - 1].rstrip() + "…"


# Sections


def summary_sections(
    content: dict[str, Any], *, show_products: bool, protocols_shown: frozenset[str]
) -> list[SectionOut]:
    """Story 3.3's sections, in order, leaving out empty ones. Products and test links only for
    adults and never during an emergency or crisis hold (`show_products`). A step's Wellness
    Protocols link only while that protocol is published and suitable for the age
    (`protocols_shown`)."""
    sections: list[SectionOut] = []

    def add(key: str, **values: Any) -> None:
        sections.append(SectionOut(key=key, title=SUMMARY_TITLES[key], **values))

    add("what_im_hearing", text=content["what_im_hearing"])
    if content.get("hypothalamic_connection"):
        add("hypothalamic_connection", text=content["hypothalamic_connection"])
    add("what_this_may_mean", text=content["what_this_may_mean"])
    if content.get("questions_for_provider"):
        add(
            "questions_for_provider",
            items=[SectionItemOut(text=line) for line in content["questions_for_provider"]],
        )
    if content.get("tests_worth_discussing"):
        add(
            "tests_worth_discussing",
            items=[
                SectionItemOut(
                    text=test["name"],
                    detail=test.get("why"),
                    # Deborah's link for the test: an information link, nothing is ordered.
                    url=test.get("url") if show_products else None,
                )
                for test in content["tests_worth_discussing"]
            ],
        )
    if content.get("what_you_can_do_now"):
        add(
            "what_you_can_do_now",
            items=[
                SectionItemOut(
                    text=step["text"],
                    protocol=(
                        step.get("protocol") if step.get("protocol") in protocols_shown else None
                    ),
                )
                for step in content["what_you_can_do_now"]
            ],
        )
    products = summary_products(content, show_products=show_products)
    if products:
        add(
            "recommendations",
            items=[
                SectionItemOut(
                    text=product["label"],
                    url=product["url"],
                    detail=product.get("why"),
                    kind=product["kind"],
                    directions=(
                        how_to_take(product.get("label_directions"))
                        if product["kind"] == "genesis_product"
                        else None
                    ),
                )
                for product in products
            ],
            note=(
                PRODUCT_NOTE
                if any(product["kind"] == "genesis_product" for product in products)
                else None
            ),
        )
    if content.get("recommended_next_steps"):
        add(
            "recommended_next_steps",
            items=[SectionItemOut(text=line) for line in content["recommended_next_steps"]],
        )
    if content.get("stage") == "first_look" and content.get("still_needed"):
        add("still_needed", items=[SectionItemOut(text=line) for line in content["still_needed"]])
    add("word_from_the_oracle", text=content["word_from_the_oracle"])
    return sections


def summary_products(content: dict[str, Any], *, show_products: bool) -> list[dict[str, Any]]:
    return list(content.get("recommendations") or []) if show_products else []


def notes_sections(content: dict[str, Any]) -> list[SectionOut]:
    """Story 3.4's "For My Provider" sections, in the template's order."""
    sections: list[SectionOut] = []

    def add(key: str, **values: Any) -> None:
        sections.append(SectionOut(key=key, title=NOTES_TITLES[key], **values))

    add("chief_complaint", text=content["chief_complaint"])
    add(
        "clinical_context",
        text=content["clinical_context"],
        # Listed as the client reported them, with no interpretation.
        items=[
            SectionItemOut(text=f"{lab['test']}: {lab['value']}", kind="reported_lab")
            for lab in content.get("reported_lab_values") or []
        ],
    )
    labs = sorted(content.get("labs_requested") or [], key=lambda lab: not lab.get("primary"))
    add(
        "labs_requested",
        items=[
            SectionItemOut(
                text=lab["name"],
                detail=lab.get("reason"),
                kind="primary" if lab.get("primary") else "also_request",
            )
            for lab in labs
        ],
    )
    add("questions", items=[SectionItemOut(text=line) for line in content.get("questions") or []])
    add(
        "medications",
        items=[SectionItemOut(text=line) for line in content.get("medications") or []],
        note=GENESIS_GOLD_NOTE if content.get("taking_genesis_gold") else None,
    )
    red_flags = content.get("red_flags") or []
    add(
        "red_flags",
        text=None if red_flags else NO_RED_FLAGS,
        items=[SectionItemOut(text=line) for line in red_flags],
    )
    recommendation = content["recommendation"]
    if content.get("referral"):
        recommendation = f"{recommendation}\n\n{content['referral']}"
    add("recommendation", text=recommendation)
    return sections


def notes_disclosure(content: dict[str, Any]) -> str | None:
    """Only when the notes mention Genesis products or affiliate links (3.4)."""
    if content.get("mentions_products") or content.get("taking_genesis_gold"):
        return NOTES_DISCLOSURE
    return None


# The printable document


@dataclass(frozen=True)
class Document:
    title: str
    subtitle: str | None
    sections: list[SectionOut]
    disclaimer: str
    header: list[tuple[str, str]] = field(default_factory=list)  # (label, value)
    intro_title: str | None = None
    intro: str | None = None
    disclosure: str | None = None


def _item_line(section: SectionOut, item: SectionItemOut) -> str:
    text = item.text
    if section.key == "labs_requested" and item.kind == "also_request":
        text = f"{ALSO_REQUEST}: {text}"
    if item.detail:
        text = f"{text}: {item.detail}"
    if item.url:
        text = f"{text} ({item.url})"
    return text


def _items_heading(section: SectionOut) -> str | None:
    if section.key == "clinical_context" and section.items:
        return REPORTED_LABS
    return None


def to_text(document: Document) -> str:
    """Copy text (3.5): plain text for an email or a patient portal."""
    lines = [document.title]
    if document.subtitle:
        lines.append(document.subtitle)
    if document.header:
        lines.append("")
        lines.extend(f"{label}: {value}" for label, value in document.header)
    if document.intro:
        lines.append("")
        if document.intro_title:
            lines.append(document.intro_title)
        lines.append(document.intro)
    for section in document.sections:
        lines.extend(["", section.title])
        if section.text:
            lines.append(section.text)
        heading = _items_heading(section)
        if heading:
            lines.append(f"{heading}:")
        for item in section.items:
            lines.append(f"- {_item_line(section, item)}")
            if item.directions:
                lines.append(f"  {item.directions}")
        if section.note:
            lines.append(section.note)
    if document.disclosure:
        lines.extend(["", DISCLOSURE_TITLE, document.disclosure])
    lines.extend(["", document.disclaimer])
    return "\n".join(lines) + "\n"


class _PDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", size=9)
        self.cell(0, 10, f"Page {self.page_no()} of {{nb}}", align="C")


def _pdf_text(value: str) -> str:
    """The PDF's built-in fonts cover Windows-1252 only (typographic quotes and ® included);
    anything else prints as "?". Before production, embed a Unicode font so names in every
    script print (docs/decisions/phase-5-guidance-and-notes.md)."""
    return value.encode("cp1252", errors="replace").decode("cp1252")


def to_pdf(document: Document, paper: Paper) -> bytes:
    """Download PDF and Print (3.5): Letter or A4, readable sizes, black on white."""
    pdf = _PDF(format="letter" if paper == "letter" else "A4")
    pdf.core_fonts_encoding = "windows-1252"
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_title(_pdf_text(document.title))
    pdf.set_author("Your Oracle")
    pdf.set_lang("en-US")
    pdf.add_page()

    def write(text: str, *, size: float = 11, style: str = "", height: float = 6) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, height, _pdf_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    write(document.title, size=16, style="B", height=8)
    if document.subtitle:
        write(document.subtitle, size=10)
    if document.header:
        pdf.ln(3)
        for label, value in document.header:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(45, 6, _pdf_text(f"{label}:"))
            write(value)
    if document.intro:
        pdf.ln(3)
        if document.intro_title:
            write(document.intro_title, size=12, style="B", height=7)
        write(document.intro)
    for section in document.sections:
        pdf.ln(3)
        write(section.title, size=12, style="B", height=7)
        if section.text:
            write(section.text)
        heading = _items_heading(section)
        if heading:
            write(f"{heading}:", style="I")
        for item in section.items:
            write(f"• {_item_line(section, item)}")
            if item.directions:
                write(f"   {item.directions}")
        if section.note:
            write(section.note, style="I")
    if document.disclosure:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(
            0,
            5,
            _pdf_text(f"{DISCLOSURE_TITLE}: {document.disclosure}"),
            border=1,
            padding=2,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    pdf.ln(4)
    write(document.disclaimer, size=10, style="I", height=5)
    return bytes(pdf.output())


# File names


def _file_part(value: str) -> str:
    """A piece of a file name: characters file systems refuse become hyphens."""
    value = re.sub(r'[\\/:*?"<>|\s]+', "-", value)
    value = "".join(char for char in value if unicodedata.category(char)[0] != "C")
    return value.strip("-.") or "Notes"


def file_name(*parts: str) -> str:
    return "_".join(_file_part(part) for part in parts) + ".pdf"


def content_disposition(name: str) -> str:
    """An attachment header with an ASCII name for old clients and the full name in UTF-8."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip("-") or "Notes.pdf"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
