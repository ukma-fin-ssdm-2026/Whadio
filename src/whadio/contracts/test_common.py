import json

import pytest
from pydantic import ValidationError

from .common import Segment, Transcript


def _segment(start: float, end: float, speaker: str | None = "Speaker 1") -> dict[str, object]:
    return {"start_seconds": start, "end_seconds": end, "speaker": speaker, "text": "Добрий день"}


def _transcript(speakers: list[str], segment_speakers: list[str | None]) -> dict[str, object]:
    segments = [_segment(i, i + 1, speaker) for i, speaker in enumerate(segment_speakers)]
    return {"language": "uk", "speakers": speakers, "segments": segments}


def test_segment_ending_before_it_starts_is_refused() -> None:
    # Arrange
    body = json.dumps(_segment(start=5.0, end=4.0))

    # Act / Assert
    with pytest.raises(ValidationError, match="must end after it starts"):
        Segment.model_validate_json(body)


def test_segment_of_zero_length_is_refused() -> None:
    # Arrange
    body = json.dumps(_segment(start=5.0, end=5.0))

    # Act / Assert
    with pytest.raises(ValidationError, match="must end after it starts"):
        Segment.model_validate_json(body)


def test_segment_accepts_whole_seconds() -> None:
    # Arrange
    body = json.dumps(_segment(start=0, end=2))

    # Act
    segment = Segment.model_validate_json(body)

    # Assert
    assert segment.end_seconds == pytest.approx(2.0)


def test_segment_with_unknown_field_is_refused() -> None:
    # Arrange
    body = json.dumps({**_segment(0, 1), "confidence": 0.9})

    # Act / Assert
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Segment.model_validate_json(body)


def test_transcript_segment_of_unknown_speaker_is_refused() -> None:
    # Arrange
    body = json.dumps(_transcript(["Speaker 1"], ["Speaker 2"]))

    # Act / Assert
    with pytest.raises(ValidationError, match="must be one of `speakers`"):
        Transcript.model_validate_json(body)


def test_transcript_with_duplicate_speakers_is_refused() -> None:
    # Arrange
    body = json.dumps(_transcript(["Speaker 1", "Speaker 1"], ["Speaker 1"]))

    # Act / Assert
    with pytest.raises(ValidationError, match="must be unique"):
        Transcript.model_validate_json(body)


def test_transcript_segment_without_speaker_is_accepted() -> None:
    # Arrange
    body = json.dumps(_transcript(["Speaker 1"], [None]))

    # Act
    transcript = Transcript.model_validate_json(body)

    # Assert
    assert transcript.segments[0].speaker is None


def test_transcript_with_a_language_name_instead_of_a_code_is_refused() -> None:
    # Arrange
    body = json.dumps({**_transcript([], []), "language": "Ukrainian"})

    # Act / Assert
    with pytest.raises(ValidationError, match="String should match pattern"):
        Transcript.model_validate_json(body)
