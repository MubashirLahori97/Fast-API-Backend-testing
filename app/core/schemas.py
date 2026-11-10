import re
import unicodedata

from pydantic import BaseModel, ConfigDict

from app.core.config import settings

# Removed from names, write-ins and labels: control characters, format characters (zero-width,
# bidi overrides, invisible tag characters), private use, surrogates, unassigned code points,
# and line and paragraph separators. Any of these can hide text or start a new line in a PDF or
# an Oracle prompt.
HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})
# Removed from chat messages: control characters other than tab and line break. Postgres
# can't store NUL at all. Format characters stay, because emoji sequences use them.
MESSAGE_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class RequestBody(BaseModel):
    """Base for request bodies.

    validate_default runs field validators on missing fields too, so a missing field gets the
    story's "please enter..." message. extra="forbid" rejects fields the client may not set,
    such as role. str_max_length stops oversized input before it reaches hashing or the database.
    """

    model_config = ConfigDict(validate_default=True, extra="forbid", str_max_length=1000)


class MessageResponse(BaseModel):
    message: str


def clean_line(value: str) -> str:
    """One line of visible text: NFKC-normalised, hidden characters removed, and runs of
    whitespace collapsed to single spaces."""
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if unicodedata.category(char) not in HIDDEN_CATEGORIES)
    return " ".join(value.split())


def clean_name(value: str) -> str:
    """A first name or a gender or pronoun write-in, which reach PDFs and the Oracle's prompts.
    Returns "" when no letter is left; callers raise their own story message for that."""
    value = clean_line(value)
    if not any(char.isalpha() for char in value):
        return ""
    if len(value) > settings.name_max_length:
        raise ValueError(f"Please keep this to {settings.name_max_length} characters or fewer.")
    return value


def clean_message(value: str) -> str:
    """A chat message: trimmed, line breaks kept, other control characters removed."""
    return MESSAGE_CONTROLS.sub("", value.replace("\r\n", "\n")).strip()
