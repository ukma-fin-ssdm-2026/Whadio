"""Ported from local-asr `src/speakers.py` (06ec281)."""

from bisect import bisect_left
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from ...contracts.common import Segment
from .diarization import SpeakerTurn
from .recognition import RecognizedSegment, Word

# The contract needs a segment to end after it starts; recognisers emit zero-length words.
_MIN_SEGMENT_SECONDS: Final = 0.01


class SpeakerIndex:
    def __init__(self, turns: Sequence[SpeakerTurn]) -> None:
        self._turns: tuple[SpeakerTurn, ...] = tuple(sorted(turns, key=lambda turn: turn.start))
        self._starts: list[float] = [turn.start for turn in self._turns]

    def speaker_of(self, start: float, end: float) -> str | None:
        """The speaker who talks longest within the interval, else the one whose turn is nearest."""
        if not self._turns:
            return None
        before_end = bisect_left(self._starts, end)
        if before_end == 0:
            return self._turns[0].speaker
        talk: dict[str, float] = {}
        for turn in self._turns[:before_end]:
            overlap = min(turn.end, end) - max(turn.start, start)
            if overlap > 0:
                talk[turn.speaker] = talk.get(turn.speaker, 0.0) + overlap
        if talk:
            return max(talk, key=talk.__getitem__)
        middle = (start + end) / 2
        nearest = min(self._turns, key=lambda turn: abs((turn.start + turn.end) / 2 - middle))
        return nearest.speaker


@dataclass(frozen=True, slots=True)
class SpeakerAttribution:
    speakers: tuple[str, ...]
    segments: tuple[Segment, ...]


def attribute_speakers(
    turns: Sequence[SpeakerTurn], recognized: Sequence[RecognizedSegment]
) -> SpeakerAttribution:
    """Split the segments where the speaker changes and label speakers `Speaker 1`, `Speaker 2`
    and so on in order of their first words."""
    index = SpeakerIndex(turns)
    labels: dict[str, str] = {}
    segments: list[Segment] = []
    for piece in (piece for segment in recognized for piece in _pieces(segment, index)):
        text = piece.text.strip()
        if not text:
            continue
        label = (
            None
            if piece.speaker is None
            else labels.setdefault(piece.speaker, f"Speaker {len(labels) + 1}")
        )
        segments.append(
            Segment(
                start_seconds=piece.start,
                end_seconds=max(piece.end, piece.start + _MIN_SEGMENT_SECONDS),
                speaker=label,
                text=text,
            )
        )
    return SpeakerAttribution(speakers=tuple(labels.values()), segments=tuple(segments))


@dataclass(frozen=True, slots=True)
class _Piece:
    start: float
    end: float
    text: str
    speaker: str | None


def _pieces(segment: RecognizedSegment, index: SpeakerIndex) -> Iterator[_Piece]:
    if not segment.words:
        speaker = index.speaker_of(segment.start, segment.end)
        yield _Piece(segment.start, segment.end, segment.text, speaker)
        return
    group: list[Word] = []
    speaker: str | None = None
    for word in segment.words:
        word_speaker = index.speaker_of(word.start, word.end)
        if group and word_speaker != speaker:
            yield _joined(group, speaker)
            group = []
        speaker = word_speaker
        group.append(word)
    yield _joined(group, speaker)


def _joined(words: Sequence[Word], speaker: str | None) -> _Piece:
    return _Piece(words[0].start, words[-1].end, "".join(word.text for word in words), speaker)
