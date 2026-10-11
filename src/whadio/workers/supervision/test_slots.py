import asyncio
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from uuid import uuid4

import pytest
from pydantic import HttpUrl, TypeAdapter

from ...contracts.common import JobKind, Transcript
from ...contracts.queues import TRANSCRIPTION_REQUESTS
from ...contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from .jobs import RunFailure, WorkerSpec
from .slots import ProcessSlot, SlotPool, SlotStartupError, slot_program

type _Result = TranscriptReady | TranscriptionFailed

_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)
_JOB_TIMEOUT = timedelta(seconds=30)
_STARTUP_TIMEOUT = timedelta(seconds=30)
_EXIT_TIMEOUT = timedelta(seconds=30)
_RESULTS = TypeAdapter[_Result](_Result)
_FAILURES = {
    RunFailure.CRASHED: TranscriptionFailure.WORKER_CRASHED,
    RunFailure.TIMED_OUT: TranscriptionFailure.TIMED_OUT,
    RunFailure.ERRORED: TranscriptionFailure.INTERNAL_ERROR,
}


def _failed(job: TranscriptionRequested, failure: RunFailure) -> _Result:
    return TranscriptionFailed(
        job_id=job.job_id, meeting_id=job.meeting_id, finished_at=_AT, reason=_FAILURES[failure]
    )


def _transcribe(job: TranscriptionRequested) -> _Result:
    if job.language == "xx":
        os._exit(3)
    return TranscriptReady(
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        finished_at=_AT,
        model_name="echo",
        duration_seconds=0,
        transcript=Transcript(language=job.language or "uk", speakers=(), segments=()),
    )


def _interrupt_and_transcribe(job: TranscriptionRequested) -> _Result:
    os.kill(os.getpid(), signal.SIGINT)
    time.sleep(0.2)
    return _transcribe(job)


def _hang(_job: TranscriptionRequested) -> _Result:
    time.sleep(60)
    raise AssertionError


def _raise(_job: TranscriptionRequested) -> _Result:
    raise RuntimeError


def _transcriber() -> Callable[[TranscriptionRequested], _Result]:
    return _transcribe


def _interrupted_transcriber() -> Callable[[TranscriptionRequested], _Result]:
    return _interrupt_and_transcribe


def _hanger() -> Callable[[TranscriptionRequested], _Result]:
    return _hang


def _raiser() -> Callable[[TranscriptionRequested], _Result]:
    return _raise


def _broken() -> Callable[[TranscriptionRequested], _Result]:
    raise RuntimeError


def _never_ready() -> Callable[[TranscriptionRequested], _Result]:
    time.sleep(60)
    raise AssertionError


_SPEC = WorkerSpec(
    name="test-slot",
    queue=TRANSCRIPTION_REQUESTS,
    kind=JobKind.TRANSCRIPTION,
    job_type=TranscriptionRequested,
    failure_result=_failed,
)


def _job(language: str = "uk") -> TranscriptionRequested:
    return TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(url=HttpUrl("http://localhost:8333/recordings/a"), expires_at=_AT),
        language=language,
        glossary=(),
    )


def _slot(
    build_handler: Callable[[], Callable[[TranscriptionRequested], _Result]],
    timeout: timedelta = _JOB_TIMEOUT,
    startup_timeout: timedelta = _STARTUP_TIMEOUT,
) -> ProcessSlot[TranscriptionRequested, _Result]:
    return ProcessSlot(
        slot_program(_SPEC, build_handler),
        _RESULTS,
        timeout=timeout,
        startup_timeout=startup_timeout,
    )


async def _run_jobs(
    slot: ProcessSlot[TranscriptionRequested, _Result], *jobs: TranscriptionRequested
) -> list[_Result]:
    await slot.start()
    try:
        return [await slot.run(job) for job in jobs]
    finally:
        await slot.stop()


async def _processes_left_after_a_failed_start(
    pool: SlotPool[TranscriptionRequested, _Result],
) -> list[BaseProcess]:
    with pytest.RaisesGroup(SlotStartupError):
        await pool.start()
    return multiprocessing.active_children()


def _hold(_slot: ProcessSlot[TranscriptionRequested, _Result]) -> None:
    threading.Event().wait()


def _start_a_slot_and_exit_still_holding_it() -> None:
    slot = _slot(_transcriber)
    asyncio.run(slot.start())
    threading.Thread(target=_hold, args=(slot,), daemon=True).start()


def _exit_code(process: BaseProcess) -> int | None:
    process.start()
    try:
        process.join(_EXIT_TIMEOUT.total_seconds())
        return process.exitcode
    finally:
        process.kill()
        process.join()


def test_slot_returns_the_result_of_its_child() -> None:
    # Arrange
    job = _job()

    # Act
    [result] = asyncio.run(_run_jobs(_slot(_transcriber), job))

    # Assert
    assert isinstance(result, TranscriptReady)


def test_slot_reports_a_child_that_dies_during_a_job_as_crashed() -> None:
    # Arrange
    job = _job(language="xx")

    # Act
    [result] = asyncio.run(_run_jobs(_slot(_transcriber), job))

    # Assert
    assert result == _failed(job, RunFailure.CRASHED)


def test_slot_runs_the_next_job_in_a_new_child_after_a_crash() -> None:
    # Arrange
    jobs = (_job(language="xx"), _job(language="uk"))

    # Act
    [_, result] = asyncio.run(_run_jobs(_slot(_transcriber), *jobs))

    # Assert
    assert isinstance(result, TranscriptReady)


def test_slot_child_finishes_its_job_when_ctrl_c_reaches_it() -> None:
    # Arrange
    job = _job()

    # Act
    [result] = asyncio.run(_run_jobs(_slot(_interrupted_transcriber), job))

    # Assert
    assert isinstance(result, TranscriptReady)


def test_slot_stops_a_job_that_runs_past_its_timeout() -> None:
    # Arrange
    job = _job()

    # Act
    [result] = asyncio.run(_run_jobs(_slot(_hanger, timeout=timedelta(seconds=1)), job))

    # Assert
    assert result == _failed(job, RunFailure.TIMED_OUT)


def test_slot_turns_an_unexpected_error_into_an_internal_error() -> None:
    # Arrange
    job = _job()

    # Act
    [result] = asyncio.run(_run_jobs(_slot(_raiser), job))

    # Assert
    assert result == _failed(job, RunFailure.ERRORED)


def test_slot_refuses_to_start_when_its_child_cannot_build_the_handler() -> None:
    # Arrange
    slot = _slot(_broken)

    # Act / Assert
    with pytest.raises(SlotStartupError, match="exited while starting"):
        asyncio.run(slot.start())


def test_worker_exits_while_it_still_holds_a_slot_it_never_stopped() -> None:
    # Arrange
    worker = multiprocessing.get_context("spawn").Process(
        target=_start_a_slot_and_exit_still_holding_it
    )

    # Act
    exit_code = _exit_code(worker)

    # Assert
    assert exit_code == 0


def test_pool_that_cannot_start_every_slot_leaves_no_process_running() -> None:
    # Arrange
    pool = SlotPool(
        [_slot(_transcriber), _slot(_never_ready, startup_timeout=timedelta(seconds=5))]
    )

    # Act
    processes = asyncio.run(_processes_left_after_a_failed_start(pool))

    # Assert
    assert processes == []
