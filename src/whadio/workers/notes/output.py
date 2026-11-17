import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ...contracts.notes import MeetingName, NotesFailure
from .errors import NotesError

_NAME: Final = TypeAdapter(MeetingName)
_FENCE: Final = "```"


@dataclass(frozen=True, slots=True)
class ParsedNotes:
    proposed_name: str
    content: str


def parse_notes(text: str, headings: Sequence[str]) -> ParsedNotes:
    title, _, content = _unfenced(text.strip()).partition("\n")
    if not title.startswith("# "):
        raise NotesError(NotesFailure.INVALID_OUTPUT)
    try:
        name = _NAME.validate_python(" ".join(title.removeprefix("# ").split()))
    except ValidationError:
        raise NotesError(NotesFailure.INVALID_OUTPUT) from None
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
