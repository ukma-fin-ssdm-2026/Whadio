import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage, AbstractQueue
from pydantic import HttpUrl

from ...contracts.common import JobKind, Transcript
from ...contracts.queues import PROCESSING_RESULTS, TRANSCRIPTION_REQUESTS, QueueSpec
from ...contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from ...shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ...shared.telemetry import RuntimeActivity
from .jobs import IResultMessage, RunFailure, WorkerSpec
from .supervisor import ConsumerOptions, JobSupervisor, WorkerFailedError, serve_jobs

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
_OPTIONS = ConsumerOptions(
    concurrency=1, consumer_timeout=timedelta(minutes=1), shutdown_grace=timedelta(seconds=1)
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
    def __init__(
        self, *, blocks: bool = False, fails: bool = False, fails_to_start: bool = False
    ) -> None:
        self._blocks: bool = blocks
        self._fails: bool = fails
        self._fails_to_start: bool = fails_to_start
        self.stopped: bool = False

    async def start(self) -> None:
        if self._fails_to_start:
            raise RuntimeError("the models cannot load")

    async def run(self, _job: TranscriptionRequested) -> _Result:
        if self._fails:
            raise RuntimeError("the worker process cannot start")
        if self._blocks:
            await asyncio.Event().wait()
        return _READY

    async def stop(self) -> None:
        self.stopped = True


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


def _isolated_spec() -> WorkerSpec[TranscriptionRequested, _Result]:
    suffix = uuid4().hex
    return replace(
        _SPEC,
        queue=QueueSpec(f"test.supervisor.{suffix}", TRANSCRIPTION_REQUESTS.arguments),
        results=QueueSpec(f"test.results.{suffix}", PROCESSING_RESULTS.arguments),
    )


async def _publish_job(
    channel: AbstractChannel,
    broker: BrokerSettings,
    spec: WorkerSpec[TranscriptionRequested, _Result],
) -> None:
    await MessagePublisher(channel, broker.user).publish(
        spec.queue.name,
        _JOB.model_dump_json().encode(),
        message_type=_JOB.type,
        correlation_id=str(_JOB.job_id),
    )


async def _first_message(queue: AbstractQueue) -> AbstractIncomingMessage:
    async with queue.iterator() as messages:
        async for message in messages:
            await message.ack()
            return message
    raise AssertionError(f"{queue.name} closed without a message")


async def _serve_a_job_that_fails(broker: BrokerSettings) -> tuple[BaseException | None, bool]:
    spec = _isolated_spec()
    async with await connect(broker, name="supervisor-test") as connection:
        channel = await connection.channel()
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        results = await declare_queue(channel, spec.results.name, spec.results.arguments)
        try:
            await _publish_job(channel, broker, spec)
            worker = serve_jobs(spec, _Runner(fails=True), broker, _OPTIONS, asyncio.Event())
            async with asyncio.timeout(30):
                (error,) = await asyncio.gather(worker, return_exceptions=True)
                returned = await _first_message(jobs)
        finally:
            await jobs.delete(if_unused=False, if_empty=False)
            await results.delete(if_unused=False, if_empty=False)
    return error, returned.redelivered is True


async def _serve_until_the_job_queue_is_deleted(broker: BrokerSettings) -> BaseException | None:
    spec = _isolated_spec()
    worker = asyncio.create_task(
        serve_jobs(spec, _Runner(blocks=True), broker, _OPTIONS, asyncio.Event())
    )
    async with await connect(broker, name="supervisor-test") as connection:
        channel = await connection.channel()
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        results = await declare_queue(channel, spec.results.name, spec.results.arguments)
        try:
            await _publish_job(channel, broker, spec)
            async with asyncio.timeout(30):
                await _first_message(results)
                await jobs.delete(if_unused=False, if_empty=False)
                (error,) = await asyncio.gather(worker, return_exceptions=True)
        finally:
            await results.delete(if_unused=False, if_empty=False)
    return error


async def _serve_until_the_runner_fails_to_start(broker: BrokerSettings, runner: _Runner) -> None:
    spec = _isolated_spec()
    async with await connect(broker, name="supervisor-test") as connection:
        channel = await connection.channel()
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        results = await declare_queue(channel, spec.results.name, spec.results.arguments)
        try:
            worker = serve_jobs(spec, runner, broker, _OPTIONS, asyncio.Event())
            async with asyncio.timeout(30):
                await asyncio.gather(worker, return_exceptions=True)
        finally:
            await jobs.delete(if_unused=False, if_empty=False)
            await results.delete(if_unused=False, if_empty=False)


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


@pytest.mark.slow
def test_worker_stops_with_an_error_when_handling_a_job_fails(
    rabbitmq_settings: BrokerSettings,
) -> None:
    # Act
    error, _ = asyncio.run(_serve_a_job_that_fails(rabbitmq_settings))

    # Assert
    assert isinstance(error, WorkerFailedError)


@pytest.mark.slow
def test_job_whose_handling_failed_goes_back_to_the_queue(
    rabbitmq_settings: BrokerSettings,
) -> None:
    # Act
    _, redelivered = asyncio.run(_serve_a_job_that_fails(rabbitmq_settings))

    # Assert
    assert redelivered


@pytest.mark.slow
def test_worker_stops_with_an_error_when_the_broker_cancels_its_consumer(
    rabbitmq_settings: BrokerSettings,
) -> None:
    # Act
    error = asyncio.run(_serve_until_the_job_queue_is_deleted(rabbitmq_settings))

    # Assert
    assert isinstance(error, WorkerFailedError)


@pytest.mark.slow
def test_worker_stops_its_runner_when_the_runner_fails_to_start(
    rabbitmq_settings: BrokerSettings,
) -> None:
    # Arrange
    runner = _Runner(fails_to_start=True)

    # Act
    asyncio.run(_serve_until_the_runner_fails_to_start(rabbitmq_settings, runner))

    # Assert
    assert runner.stopped


def test_runtime_activity_releases_capacity_when_a_job_is_cancelled() -> None:
    # Arrange
    activity = RuntimeActivity("asr", 1, "test-model")
    journal = _Journal()

    async def scenario() -> tuple[int, int]:
        supervisor = JobSupervisor(
            _SPEC, _Runner(blocks=True), _Publisher(journal), activity=activity
        )
        task = asyncio.create_task(
            supervisor.handle(_Delivery(_JOB.model_dump_json().encode(), journal))
        )
        await asyncio.sleep(0)
        during = activity.active
        # Act
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return during, activity.active

    found = asyncio.run(scenario())
    # Assert
    assert found == (1, 0)
