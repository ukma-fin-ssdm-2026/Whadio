import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ...contracts.common import JobKind, Transcript
from ...contracts.notes import (
    MeetingBrief,
    NotesFailed,
    NotesFailure,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)
from ...contracts.queues import NOTES_REQUESTS
from .jobs import RunFailure, WorkerSpec
from .runners import InlineRunner

type _Result = NotesReady | NotesFailed

_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)
_FAILURES = {
    RunFailure.CRASHED: NotesFailure.INTERNAL_ERROR,
    RunFailure.TIMED_OUT: NotesFailure.TIMED_OUT,
    RunFailure.ERRORED: NotesFailure.INTERNAL_ERROR,
}


def _failed(job: NotesRequested, failure: RunFailure) -> _Result:
    return NotesFailed(
        job_id=job.job_id, meeting_id=job.meeting_id, finished_at=_AT, reason=_FAILURES[failure]
    )


_SPEC = WorkerSpec(
    name="test-inline",
    queue=NOTES_REQUESTS,
    kind=JobKind.NOTES,
    job_type=NotesRequested,
    failure_result=_failed,
)
_JOB = NotesRequested(
    job_id=uuid4(),
    meeting_id=uuid4(),
    preset=NotesPreset.SUMMARY,
    meeting=MeetingBrief(name=None, recorded_at=_AT),
    transcript=Transcript(language="uk", speakers=(), segments=()),
    context=(),
    glossary=(),
)
_READY = NotesReady(
    job_id=_JOB.job_id,
    meeting_id=_JOB.meeting_id,
    finished_at=_AT,
    preset=NotesPreset.SUMMARY,
    provider=NotesProvider.ANTHROPIC,
    model_name="claude-sonnet-5-5",
    content="## Summary\n\nNothing was said.",
    proposed_name="Silent call",
    context_meeting_ids=(),
)


async def _write_notes(_job: NotesRequested) -> _Result:
    return _READY


async def _never_finish(_job: NotesRequested) -> _Result:
    await asyncio.Event().wait()
    raise AssertionError


async def _fail(_job: NotesRequested) -> _Result:
    raise RuntimeError


def test_inline_runner_returns_the_result_of_its_handler() -> None:
    # Arrange
    runner = InlineRunner(_SPEC, _write_notes, timeout=timedelta(seconds=5))

    # Act
    result = asyncio.run(runner.run(_JOB))

    # Assert
    assert result == _READY


def test_inline_runner_turns_an_overrun_into_the_timed_out_result() -> None:
    # Arrange
    runner = InlineRunner(_SPEC, _never_finish, timeout=timedelta(milliseconds=50))

    # Act
    result = asyncio.run(runner.run(_JOB))

    # Assert
    assert result == _failed(_JOB, RunFailure.TIMED_OUT)


def test_inline_runner_turns_an_unexpected_error_into_the_errored_result() -> None:
    # Arrange
    runner = InlineRunner(_SPEC, _fail, timeout=timedelta(seconds=5))

    # Act
    result = asyncio.run(runner.run(_JOB))

    # Assert
    assert result == _failed(_JOB, RunFailure.ERRORED)
