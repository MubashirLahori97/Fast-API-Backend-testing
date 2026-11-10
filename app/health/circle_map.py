"""Story 6.1's Hypothalamus Circle Map: Deborah's predefined map, with the profile's symptoms
highlighted from its health profile and its conversations (the Oracle saves symptoms from
conversations into the health profile, 3.1), to view, download and print.

The map is data, read from circle_map.json in this package or from the file named by
`settings.health_circle_map_path`. **The file in this package is a placeholder**, not Deborah's
map, which we don't have yet: replace it when her map is in. Each symptom on the map lists the
symptom checklist items (`question_key.choice_code`, app/health/questions.json) that highlight
it. The file is checked when the app starts, so a broken one stops the API.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpdf import FPDF, XPos, YPos

from app.core.config import settings
from app.health.bank import BANK

DEFAULT_PATH = Path(__file__).with_name("circle_map.json")
# Story 6.1's line, shown with the map.
NOTICE = "This map shows how symptoms can connect to the hypothalamus. It isn’t a diagnosis."
FILE_NAME = "hypothalamus-circle-map.pdf"


@dataclass(frozen=True)
class MapSymptom:
    key: str
    label: str
    matches: tuple[tuple[str, str], ...]  # (question key, checklist code)


@dataclass(frozen=True)
class MapArea:
    key: str
    label: str
    symptoms: tuple[MapSymptom, ...]


@dataclass(frozen=True)
class CircleMap:
    version: str
    placeholder: bool
    title: str
    centre: str
    areas: tuple[MapArea, ...]


def _fail(problem: str) -> None:
    raise ValueError(f"The Hypothalamus Circle Map file is invalid: {problem}")


def _text(data: dict, name: str, where: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        _fail(f"{where} needs a '{name}'")
    return value


def load(path: Path) -> CircleMap:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("areas"), list) or not data["areas"]:
        _fail("it needs a list of 'areas'")
    areas = []
    area_keys: set[str] = set()
    for area in data["areas"]:
        if not isinstance(area, dict) or not isinstance(area.get("symptoms"), list):
            _fail("each area needs a list of 'symptoms'")
        key = _text(area, "key", "an area")
        if key in area_keys:
            _fail(f"area '{key}' repeats")
        area_keys.add(key)
        symptoms = []
        symptom_keys: set[str] = set()
        for symptom in area["symptoms"]:
            if not isinstance(symptom, dict) or not isinstance(symptom.get("matches"), list):
                _fail(f"each symptom in '{key}' needs a list of 'matches'")
            symptom_key = _text(symptom, "key", f"a symptom in '{key}'")
            if symptom_key in symptom_keys:
                _fail(f"symptom '{symptom_key}' repeats in '{key}'")
            symptom_keys.add(symptom_key)
            matches = []
            for match in symptom["matches"]:
                question_key, _, code = str(match).partition(".")
                question = BANK.question(question_key)
                if question is None or question.kind != "checklist" or code not in question.codes:
                    _fail(f"'{match}' isn't a symptom checklist item in the question bank")
                matches.append((question_key, code))
            symptoms.append(
                MapSymptom(
                    key=symptom_key,
                    label=_text(symptom, "label", f"symptom '{symptom_key}'"),
                    matches=tuple(matches),
                )
            )
        areas.append(MapArea(key=key, label=_text(area, "label", key), symptoms=tuple(symptoms)))
    return CircleMap(
        version=_text(data, "version", "the map"),
        placeholder=data.get("status") == "placeholder",
        title=_text(data, "title", "the map"),
        centre=_text(data, "centre", "the map"),
        areas=tuple(areas),
    )


MAP = load(
    Path(settings.health_circle_map_path) if settings.health_circle_map_path else DEFAULT_PATH
)


def ticked(answers: dict[str, Any]) -> set[tuple[str, str]]:
    """The checklist items ticked in these answers (the ones that apply to the profile)."""
    items = set()
    for key, answer in answers.items():
        question = BANK.question(key)
        if question is None or question.kind != "checklist":
            continue
        value = answer.get("value") or {}
        items.update((key, code) for code in value.get("selected", []))
    return items


def highlighted(symptom: MapSymptom, items: set[tuple[str, str]]) -> bool:
    return any(match in items for match in symptom.matches)


# The downloadable and printable version (6.1: "view, download and print")


def _pdf_text(value: str) -> str:
    """The built-in fonts cover Windows-1252 only (the ’ in the notice included)."""
    return value.encode("cp1252", errors="replace").decode("cp1252")


def to_pdf(first_name: str, items: set[tuple[str, str]]) -> bytes:
    """One page: the hypothalamus in the middle, the map's areas around it (shaded where a
    symptom is highlighted), then each area's symptoms with the highlighted ones marked, and the
    story's notice. A plain drawing until Deborah's graphic replaces it."""
    pdf = FPDF(format="letter")
    pdf.core_fonts_encoding = "windows-1252"
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_title(_pdf_text(MAP.title))
    pdf.set_author("Your Oracle")
    pdf.set_lang("en-US")
    pdf.add_page()

    def write(text: str, *, size: float = 11, style: str = "", height: float = 6) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, height, _pdf_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    write(MAP.title, size=16, style="B", height=8)
    if first_name:
        write(f"For {first_name}", size=10)
    write(NOTICE, size=10, style="I")

    # The ring of circles.
    ring, small, big = 48, 17, 20
    centre_x, centre_y = pdf.w / 2, pdf.get_y() + ring + small + 4
    pdf.set_line_width(0.4)
    count = len(MAP.areas)
    for index, area in enumerate(MAP.areas):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        x, y = centre_x + ring * math.cos(angle), centre_y + ring * math.sin(angle)
        lit = any(highlighted(symptom, items) for symptom in area.symptoms)
        pdf.line(centre_x, centre_y, x, y)
        pdf.set_fill_color(*((255, 214, 153) if lit else (255, 255, 255)))
        pdf.circle(x=x, y=y, radius=small, style="FD")
        pdf.set_font("Helvetica", "B" if lit else "", 8)
        pdf.set_xy(x - small + 2, y - 5)
        pdf.multi_cell(2 * small - 4, 3.5, _pdf_text(area.label), align="C")
    pdf.set_fill_color(230, 230, 230)
    pdf.circle(x=centre_x, y=centre_y, radius=big, style="FD")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(centre_x - big, centre_y - 2.5)
    pdf.cell(2 * big, 5, _pdf_text(MAP.centre), align="C")

    pdf.set_xy(pdf.l_margin, centre_y + ring + small + 6)
    write("Highlighted symptoms are in bold, marked •.", size=9, style="I")
    for area in MAP.areas:
        pdf.ln(2)
        write(area.label, size=12, style="B", height=7)
        for symptom in area.symptoms:
            if highlighted(symptom, items):
                write(f"• {symptom.label}", style="B")
            else:
                write(f"   {symptom.label}")
    if MAP.placeholder:
        pdf.ln(3)
        write("Placeholder map: Deborah’s map will replace it.", size=9, style="I")
    return bytes(pdf.output())
