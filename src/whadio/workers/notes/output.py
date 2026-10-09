import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ...contracts.notes import NotesFailure
from .errors import NotesError

MAX_NAME_LENGTH: Final = 200
_FENCE: Final = "```"


@dataclass(frozen=True, slots=True)
class ParsedNotes:
    proposed_name: str
    content: str


def parse_notes(text: str, headings: Sequence[str]) -> ParsedNotes:
    title, _, content = _unfenced(text.strip()).partition("\n")
    if not title.startswith("# "):
        raise NotesError(NotesFailure.INVALID_OUTPUT)
    name = " ".join(title.removeprefix("# ").split())
    if not name or len(name) > MAX_NAME_LENGTH or not name.isprintable():
        raise NotesError(NotesFailure.INVALID_OUTPUT)
    content = content.strip()
    found = [_normalise(line[3:]) for line in content.splitlines() if line.startswith("## ")]
    if found != [_normalise(heading) for heading in headings]:
        raise NotesError(NotesFailure.INVALID_OUTPUT)
    return ParsedNotes(proposed_name=name, content=content)


def _unfenced(text: str) -> str:
    if not (text.startswith(_FENCE) and text.endswith(_FENCE)):
        return text
    _, _, body = text.removesuffix(_FENCE).partition("\n")
    return body.strip()


def _normalise(heading: str) -> str:
    return unicodedata.normalize("NFC", heading).strip().rstrip(":").casefold()
