from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ..contracts.common import Segment


@dataclass(frozen=True)
class SpeakerEvent:
    """The participants seen speaking from `at_seconds` into the recording until the next event."""

    at_seconds: float
    speakers: tuple[str, ...]


class ISpeakerTimeline(Protocol):
    async def speaker_events(self, meeting_id: UUID, /) -> tuple[SpeakerEvent, ...]: ...


def resolve_speaker_names(
    events: Sequence[SpeakerEvent], segments: Sequence[Segment], duration_seconds: float
) -> dict[str, str]:
    """The participant name of each diarized label the timeline identifies unambiguously.

    Only stretches with a single participant speaking count. A label is named when one name
    covers more than half of its counted time, and only if no other label gets the same name.
    """
    ordered = sorted(events, key=lambda event: event.at_seconds)
    if not ordered:
        return {}
    ends = [event.at_seconds for event in ordered[1:]] + [duration_seconds]
    talk: dict[str, dict[str, float]] = {}
    for segment in segments:
        if segment.speaker is None:
            continue
        for event, end in zip(ordered, ends, strict=True):
            overlap = min(end, segment.end_seconds) - max(event.at_seconds, segment.start_seconds)
            if len(event.speakers) == 1 and overlap > 0:
                names = talk.setdefault(segment.speaker, {})
                names[event.speakers[0]] = names.get(event.speakers[0], 0.0) + overlap
    claims = {
        label: name
        for label, names in talk.items()
        for name in (max(names, key=names.__getitem__),)
        if names[name] > sum(names.values()) / 2
    }
    taken = Counter(claims.values())
    return {label: name for label, name in claims.items() if taken[name] == 1}
