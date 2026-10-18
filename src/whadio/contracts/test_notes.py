from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from .common import Transcript
from .notes import (
    MAX_CONTEXT_MEETINGS,
    ContextMeeting,
    MeetingBrief,
    NotesFailure,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)

_RECORDED_AT = datetime(2026, 10, 6, 16, 32, tzinfo=UTC)
_EMPTY_TRANSCRIPT = Transcript(language="uk", speakers=(), segments=())


def _request(context_size: int) -> NotesRequested:
    return NotesRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        preset=NotesPreset.SUMMARY,
        meeting=MeetingBrief(name=None, recorded_at=_RECORDED_AT),
        transcript=_EMPTY_TRANSCRIPT,
        context=tuple(
            ContextMeeting(
                meeting_id=uuid4(),
                name=f"Sync {i}",
                recorded_at=_RECORDED_AT,
                transcript=_EMPTY_TRANSCRIPT,
            )
            for i in range(context_size)
        ),
        glossary=(),
    )


def _ready(proposed_name: str) -> NotesReady:
    return NotesReady(
        job_id=uuid4(),
        meeting_id=uuid4(),
        finished_at=_RECORDED_AT,
        preset=NotesPreset.SUMMARY,
        provider=NotesProvider.ANTHROPIC,
        model_name="claude-sonnet-5-5",
        content="## Summary\n\nThe team agreed on the MVP scope.",
        proposed_name=proposed_name,
        context_meeting_ids=(),
    )


def test_notes_request_survives_a_round_trip_through_json() -> None:
    # Arrange
    request = _request(context_size=2)

    # Act
    parsed = NotesRequested.model_validate_json(request.model_dump_json())

    # Assert
    assert parsed == request


def test_notes_request_with_too_many_context_meetings_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="at most 20 items"):
        _request(context_size=MAX_CONTEXT_MEETINGS + 1)


@pytest.mark.parametrize(
    "context_size",
    [
        pytest.param(MAX_CONTEXT_MEETINGS - 1, id="bva-below-max"),
        pytest.param(MAX_CONTEXT_MEETINGS, id="bva-max"),
    ],
)
def test_notes_request_with_up_to_20_context_meetings_is_accepted(context_size: int) -> None:
    # Act
    request = _request(context_size)

    # Assert
    assert len(request.context) == context_size


@pytest.mark.parametrize(
    "length",
    [
        pytest.param(1, id="bva-min"),
        pytest.param(2, id="bva-above-min"),
        pytest.param(100, id="bva-nominal"),
        pytest.param(199, id="bva-below-max"),
        pytest.param(200, id="bva-max"),
    ],
)
def test_proposed_name_of_1_to_200_characters_is_accepted(length: int) -> None:
    # Act
    ready = _ready("x" * length)

    # Assert
    assert ready.proposed_name == "x" * length


def test_empty_proposed_name_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="at least 1 character"):
        _ready("")


def test_proposed_name_longer_than_200_characters_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="at most 200 characters"):
        _ready("x" * 201)


def test_proposed_name_of_several_lines_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="String should match pattern"):
        _ready("Sprint review\nand planning")


@pytest.mark.parametrize(
    "failure",
    [
        NotesFailure.PROVIDER_RATE_LIMITED,
        NotesFailure.PROVIDER_UNAVAILABLE,
        NotesFailure.INVALID_OUTPUT,
        NotesFailure.TIMED_OUT,
        NotesFailure.INTERNAL_ERROR,
    ],
)
def test_transient_notes_failures_are_retryable(failure: NotesFailure) -> None:
    # Act
    retryable = failure.retryable

    # Assert
    assert retryable


@pytest.mark.parametrize(
    "failure",
    [
        NotesFailure.TRANSCRIPT_TOO_LONG,
        NotesFailure.PROVIDER_AUTH_FAILED,
        NotesFailure.PROVIDER_REFUSED,
        NotesFailure.PROVIDER_REJECTED_REQUEST,
    ],
)
def test_notes_failures_that_would_repeat_are_not_retryable(failure: NotesFailure) -> None:
    # Act
    retryable = failure.retryable

    # Assert
    assert not retryable
