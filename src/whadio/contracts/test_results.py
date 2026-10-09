from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from .common import JobKind, Transcript
from .notes import NotesFailed, NotesFailure, NotesPreset, NotesProvider, NotesReady
from .results import JobStarted, ProcessingResult, parse_result
from .transcription import TranscriptionFailed, TranscriptionFailure, TranscriptReady

_JOB = UUID("0b6f3a56-2f43-4c1e-9d8a-5b7c6d4e3f21")
_MEETING = UUID("5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9")
_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)

_RESULTS: list[ProcessingResult] = [
    JobStarted(job_id=_JOB, meeting_id=_MEETING, kind=JobKind.TRANSCRIPTION, started_at=_AT),
    TranscriptReady(
        job_id=_JOB,
        meeting_id=_MEETING,
        finished_at=_AT,
        model_name="nemo-parakeet-tdt-0.6b-v3",
        duration_seconds=1.5,
        transcript=Transcript(language="uk", speakers=(), segments=()),
    ),
    TranscriptionFailed(
        job_id=_JOB,
        meeting_id=_MEETING,
        finished_at=_AT,
        reason=TranscriptionFailure.UNSUPPORTED_AUDIO,
    ),
    NotesReady(
        job_id=_JOB,
        meeting_id=_MEETING,
        finished_at=_AT,
        preset=NotesPreset.DETAILED,
        provider=NotesProvider.ANTHROPIC,
        model_name="claude-sonnet-5-5",
        content="## Overview\n\nA short call.",
        proposed_name="Short call",
        context_meeting_ids=(),
    ),
    NotesFailed(
        job_id=_JOB, meeting_id=_MEETING, finished_at=_AT, reason=NotesFailure.INVALID_OUTPUT
    ),
]


@pytest.mark.parametrize("result", [pytest.param(r, id=r.type) for r in _RESULTS])
def test_parse_result_reads_back_each_result_type(result: ProcessingResult) -> None:
    # Arrange
    body = result.model_dump_json().encode()

    # Act
    parsed = parse_result(body)

    # Assert
    assert parsed == result


def test_parse_result_refuses_a_job_request() -> None:
    # Arrange
    body = b'{"type": "transcription_requested"}'

    # Act / Assert
    with pytest.raises(ValidationError, match="does not match any of the expected tags"):
        parse_result(body)


def test_parse_result_refuses_a_body_that_is_not_json() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="Invalid JSON"):
        parse_result(b"transcript ready")
