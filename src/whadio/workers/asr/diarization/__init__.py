from dataclasses import dataclass
from typing import Protocol

from ..audio import Audio


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


class IDiarizer(Protocol):
    def diarize(self, audio: Audio) -> tuple[SpeakerTurn, ...]: ...
