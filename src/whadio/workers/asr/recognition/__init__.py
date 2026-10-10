from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ....contracts.common import GlossaryEntry
from ..audio import Audio


class RecognizerKind(StrEnum):
    PARAKEET = "parakeet"
    WHISPER = "whisper"


@dataclass(frozen=True, slots=True)
class RecognitionHints:
    language: str | None
    glossary: tuple[GlossaryEntry, ...]


@dataclass(frozen=True, slots=True)
class Word:
    """A recognised word; `text` keeps the space that separates it from the word before."""

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class RecognizedSegment:
    start: float
    end: float
    text: str
    words: tuple[Word, ...]


class ISpeechRecognizer(Protocol):
    @property
    def model_name(self) -> str: ...

    def recognize(self, audio: Audio, hints: RecognitionHints) -> tuple[RecognizedSegment, ...]: ...
