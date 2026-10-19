import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from aio_pika.abc import AbstractIncomingMessage, AbstractRobustChannel
from pydantic import ValidationError

from ...contracts.common import JobMessage
from ...contracts.queues import DEAD_LETTERS
from ...contracts.results import JobStarted
from ...shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ...shared.telemetry import RuntimeActivity, TelemetrySettings, publish_activity
from .jobs import IJobRunner, IResultMessage, WorkerSpec

logger = logging.getLogger(__name__)


class WorkerFailedError(Exception):
    pass


class IDelivery(Protocol):
    @property
    def body(self) -> bytes: ...

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool = True) -> None: ...

    async def reject(self, *, requeue: bool = False) -> None: ...


class IResultPublisher(Protocol):
    async def publish(self, result: IResultMessage) -> None: ...


class AmqpResultPublisher:
    def __init__(self, publisher: MessagePublisher, queue: str) -> None:
        self._publisher: MessagePublisher = publisher
        self._queue: str = queue

    async def publish(self, result: IResultMessage) -> None:
        await self._publisher.publish(
            self._queue,
            result.model_dump_json().encode(),
            message_type=result.type,
            correlation_id=str(result.job_id),
        )


@dataclass(frozen=True, slots=True)
class ConsumerOptions:
    concurrency: int
    consumer_timeout: timedelta
    shutdown_grace: timedelta
    activity: RuntimeActivity | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobSupervisor[J: JobMessage, R: IResultMessage]:
    def __init__(
        self,
        spec: WorkerSpec[J, R],
        runner: IJobRunner[J, R],
        publisher: IResultPublisher,
        now: Callable[[], datetime] = _utc_now,
        activity: RuntimeActivity | None = None,
    ) -> None:
        self._activity: RuntimeActivity | None = activity
        self._spec: WorkerSpec[J, R] = spec
        self._runner: IJobRunner[J, R] = runner
        self._publisher: IResultPublisher = publisher
        self._now: Callable[[], datetime] = now

    async def handle(self, delivery: IDelivery) -> None:
        try:
            job = self._spec.job_type.model_validate_json(delivery.body)
        except ValidationError as error:
            logger.warning(
                "Rejected a message from %s that is not a valid job (%d problems)",
                self._spec.queue.name,
                error.error_count(),
            )
            await delivery.reject(requeue=False)
            return
        try:
            started = JobStarted(
                job_id=job.job_id,
                meeting_id=job.meeting_id,
                kind=self._spec.kind,
                started_at=self._now(),
            )
            await self._publisher.publish(started)
            if self._activity is not None:
                self._activity.active += 1
            try:
                result = await self._runner.run(job)
            finally:
                if self._activity is not None:
                    self._activity.active -= 1
            await self._publisher.publish(result)
        except asyncio.CancelledError:
            await delivery.nack(requeue=True)
            raise
        await delivery.ack()


async def serve_jobs[J: JobMessage, R: IResultMessage](
    spec: WorkerSpec[J, R],
    runner: IJobRunner[J, R],
    broker: BrokerSettings,
    options: ConsumerOptions,
    stop: asyncio.Event,
) -> None:
    activity = options.activity
    connection = await connect(broker, name=spec.name)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=options.concurrency)
        for queue in (DEAD_LETTERS, spec.results):
            await declare_queue(channel, queue.name, queue.arguments)
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        publisher = AmqpResultPublisher(MessagePublisher(channel, broker.user), spec.results.name)
        supervisor = JobSupervisor(spec, runner, publisher, activity=activity)
        in_flight: set[asyncio.Task[None]] = set()
        failed = asyncio.Event()

        def fail() -> None:
            failed.set()
            stop.set()

        async def on_message(message: AbstractIncomingMessage) -> None:
            task = asyncio.create_task(_handle(supervisor, message, fail))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)

        def on_consumer_cancelled() -> None:
            logger.error("RabbitMQ cancelled the consumer of %s", spec.queue.name)
            fail()

        await _watch_consumer_cancel(channel, on_consumer_cancelled)
        try:
            telemetry = TelemetrySettings()
        except ValidationError:
            logger.warning("Worker telemetry configuration invalid; collection disabled")
            telemetry = None
        observation_task = (
            asyncio.create_task(publish_activity(activity, telemetry, stop))
            if activity is not None and telemetry is not None and telemetry.receiver is not None
            else None
        )
        try:
            await runner.start()
            if activity is not None:
                activity.ready = True
            # A job may hold its message for as long as its timeout allows; past the consumer
            # timeout RabbitMQ would hand the message to another worker while this one still runs.
            tag = await jobs.consume(
                on_message,
                arguments={
                    "x-consumer-timeout": int(options.consumer_timeout.total_seconds() * 1000)
                },
            )
            logger.info("Consuming %s", spec.queue.name)
            await stop.wait()
            await jobs.cancel(tag)
            await _finish(in_flight, options.shutdown_grace)
        finally:
            if observation_task is not None:
                observation_task.cancel()
                await asyncio.gather(observation_task, return_exceptions=True)
            await runner.stop()
    if failed.is_set():
        raise WorkerFailedError(f"{spec.name} stopped after a failure; the log has its cause")


async def _watch_consumer_cancel(
    channel: AbstractRobustChannel, on_cancel: Callable[[], None]
) -> None:
    # aio-pika ignores a consumer RabbitMQ cancels (a deleted queue, a consumer timeout), and a
    # reconnect replaces the underlying channel that holds the callback.
    async def register(_channel: AbstractRobustChannel | None, /) -> None:
        underlay = await channel.get_underlay_channel()
        underlay.on_consumer_cancel_callbacks.add(lambda _frame: on_cancel())

    await register(channel)
    channel.reopen_callbacks.add(register)


async def _handle[J: JobMessage, R: IResultMessage](
    supervisor: JobSupervisor[J, R], message: AbstractIncomingMessage, fail: Callable[[], None]
) -> None:
    try:
        await supervisor.handle(message)
    except Exception:
        # Left unsettled, the message returns when the worker's connection closes and the delivery
        # counts towards the limit, so one that keeps failing is dead-lettered; a nack would not.
        logger.exception("Handling a message from the job queue failed; stopping the worker")
        fail()


async def _finish(in_flight: set[asyncio.Task[None]], grace: timedelta) -> None:
    if not in_flight:
        return
    logger.info("Waiting up to %s for %d running jobs", grace, len(in_flight))
    _, pending = await asyncio.wait(in_flight, timeout=grace.total_seconds())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
