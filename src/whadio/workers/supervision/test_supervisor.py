import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import HttpUrl

from ...contracts.common import JobKind, Transcript
from ...contracts.queues import TRANSCRIPTION_REQUESTS
from ...contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from .jobs import IResultMessage, RunFailure, WorkerSpec
from .supervisor import JobSupervisor

type _Result = TranscriptReady | TranscriptionFailed

_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)
_JOB = TranscriptionRequested(
    job_id=uuid4(),
    meeting_id=uuid4(),
    audio=AudioLink(url=HttpUrl("http://localhost:8333/recordings/a"), expires_at=_AT),
    language="uk",
    glossary=(),
)
_READY = TranscriptReady(
    job_id=_JOB.job_id,
    meeting_id=_JOB.meeting_id,
    finished_at=_AT,
    model_name="echo",
    duration_seconds=0,
    transcript=Transcript(language="uk", speakers=(), segments=()),
)


def _failed(job: TranscriptionRequested, _failure: RunFailure) -> _Result:
    return TranscriptionFailed(
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        finished_at=_AT,
        reason=TranscriptionFailure.INTERNAL_ERROR,
    )


_SPEC = WorkerSpec(
    name="test-supervisor",
    queue=TRANSCRIPTION_REQUESTS,
    kind=JobKind.TRANSCRIPTION,
    job_type=TranscriptionRequested,
    failure_result=_failed,
)


class _Journal:
    def __init__(self) -> None:
        self.events: list[str] = []


class _Delivery:
    def __init__(self, body: bytes, journal: _Journal) -> None:
        self.body: bytes = body
        self._journal: _Journal = journal

    async def ack(self) -> None:
        self._journal.events.append("ack")

    async def nack(self, *, requeue: bool = True) -> None:
        self._journal.events.append(f"nack requeue={requeue}")

    async def reject(self, *, requeue: bool = False) -> None:
        self._journal.events.append(f"reject requeue={requeue}")


class _Publisher:
    def __init__(self, journal: _Journal) -> None:
        self._journal: _Journal = journal

    async def publish(self, result: IResultMessage) -> None:
        self._journal.events.append(f"publish {result.type}")


class _Runner:
    def __init__(self, *, blocks: bool = False) -> None:
        self._blocks: bool = blocks

    async def start(self) -> None:
        pass

    async def run(self, _job: TranscriptionRequested) -> _Result:
        if self._blocks:
            await asyncio.Event().wait()
        return _READY

    async def stop(self) -> None:
        pass


def _supervise(body: bytes, runner: _Runner) -> list[str]:
    journal = _Journal()
    supervisor = JobSupervisor(_SPEC, runner, _Publisher(journal), now=lambda: _AT)
    asyncio.run(supervisor.handle(_Delivery(body, journal)))
    return journal.events


async def _shut_down_during(body: bytes) -> list[str]:
    journal = _Journal()
    supervisor = JobSupervisor(_SPEC, _Runner(blocks=True), _Publisher(journal), now=lambda: _AT)
    task = asyncio.create_task(supervisor.handle(_Delivery(body, journal)))
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return journal.events


def test_job_is_acknowledged_only_after_its_result_is_published() -> None:
    # Arrange
    body = _JOB.model_dump_json().encode()

    # Act
    events = _supervise(body, _Runner())

    # Assert
    assert events == ["publish job_started", "publish transcript_ready", "ack"]


def test_message_that_is_not_a_valid_job_is_dead_lettered_without_running() -> None:
    # Arrange
    body = b'{"job_id": "not a uuid"}'

    # Act
    events = _supervise(body, _Runner())

    # Assert
    assert events == ["reject requeue=False"]


def test_job_interrupted_by_a_shutdown_goes_back_to_the_queue() -> None:
    # Arrange
    body = _JOB.model_dump_json().encode()

    # Act
    events = asyncio.run(_shut_down_during(body))

    # Assert
    assert events == ["publish job_started", "nack requeue=True"]
