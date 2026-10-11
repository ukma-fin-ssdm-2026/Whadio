import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import HttpUrl, ValidationError

from .common import GlossaryEntry
from .transcription import AudioLink, TranscriptionFailure, TranscriptionRequested

_LINK = "http://localhost:8333/recordings/meeting.mp4?X-Amz-Signature=abc"


def test_transcription_request_survives_a_round_trip_through_json() -> None:
    # Arrange
    request = TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(url=HttpUrl(_LINK), expires_at=datetime(2026, 10, 9, 18, tzinfo=UTC)),
        language=None,
        glossary=(GlossaryEntry(term="віспер", preferred_form="Whisper", description=""),),
    )

    # Act
    parsed = TranscriptionRequested.model_validate_json(request.model_dump_json())

    # Assert
    assert parsed == request


def test_transcription_request_with_a_naive_link_expiry_is_refused() -> None:
    # Arrange
    body: dict[str, object] = {
        "job_id": str(uuid4()),
        "meeting_id": str(uuid4()),
        "audio": {"url": _LINK, "expires_at": "2026-10-09T18:00:00"},
        "language": "uk",
        "glossary": [],
    }

    # Act / Assert
    with pytest.raises(ValidationError, match="timezone"):
        TranscriptionRequested.model_validate_json(json.dumps(body))


@pytest.mark.parametrize(
    "failure",
    [
        TranscriptionFailure.AUDIO_LINK_EXPIRED,
        TranscriptionFailure.STORAGE_UNAVAILABLE,
        TranscriptionFailure.WORKER_CRASHED,
        TranscriptionFailure.INTERNAL_ERROR,
    ],
)
def test_transient_transcription_failures_are_retryable(failure: TranscriptionFailure) -> None:
    # Act
    retryable = failure.retryable

    # Assert
    assert retryable


@pytest.mark.parametrize(
    "failure",
    [
        TranscriptionFailure.AUDIO_NOT_FOUND,
        TranscriptionFailure.AUDIO_TOO_LARGE,
        TranscriptionFailure.UNSUPPORTED_AUDIO,
        TranscriptionFailure.AUDIO_TOO_LONG,
        TranscriptionFailure.TIMED_OUT,
    ],
)
def test_failures_caused_by_the_recording_are_not_retryable(
    failure: TranscriptionFailure,
) -> None:
    # Act
    retryable = failure.retryable

    # Assert
    assert not retryable
