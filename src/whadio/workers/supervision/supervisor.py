import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from ...contracts.common import JobMessage
from ...contracts.queues import ALL_QUEUES, PROCESSING_RESULTS
from ...contracts.results import JobStarted
from ...shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from .jobs import IJobRunner, IResultMessage, WorkerSpec

logger = logging.getLogger(__name__)


class IDelivery(Protocol):
    @property
    def body(self) -> bytes: ...

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool = True) -> None: ...

    async def reject(self, *, requeue: bool = False) -> None: ...


class IResultPublisher(Protocol):
    async def publish(self, result: IResultMessage) -> None: ...


class AmqpResultPublisher:
    def __init__(self, publisher: MessagePublisher) -> None:
        self._publisher: MessagePublisher = publisher

    async def publish(self, result: IResultMessage) -> None:
        await self._publisher.publish(
            PROCESSING_RESULTS.name,
            result.model_dump_json().encode(),
            message_type=result.type,
            correlation_id=str(result.job_id),
        )


@dataclass(frozen=True, slots=True)
class ConsumerOptions:
    concurrency: int
    consumer_timeout: timedelta
    shutdown_grace: timedelta


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobSupervisor[J: JobMessage, R: IResultMessage]:
    def __init__(
        self,
        spec: WorkerSpec[J, R],
        runner: IJobRunner[J, R],
        publisher: IResultPublisher,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
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
            result = await self._runner.run(job)
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
    connection = await connect(broker, name=spec.name)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=options.concurrency)
        declared = {
            queue.name: await declare_queue(channel, queue.name, queue.arguments)
            for queue in ALL_QUEUES
        }
        jobs = declared[spec.queue.name]
        supervisor = JobSupervisor(
            spec, runner, AmqpResultPublisher(MessagePublisher(channel, broker.user))
        )
        in_flight: set[asyncio.Task[None]] = set()

        async def on_message(message: AbstractIncomingMessage) -> None:
            task = asyncio.create_task(_handle(supervisor, message))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)

        await runner.start()
        try:
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
            await runner.stop()


async def _handle[J: JobMessage, R: IResultMessage](
    supervisor: JobSupervisor[J, R], message: AbstractIncomingMessage
) -> None:
    try:
        await supervisor.handle(message)
    except Exception:
        # The message stays unacknowledged, so RabbitMQ delivers it again; Processing ignores the
        # duplicate results that may follow.
        logger.exception("Handling a message from the job queue failed")


async def _finish(in_flight: set[asyncio.Task[None]], grace: timedelta) -> None:
    if not in_flight:
        return
    logger.info("Waiting up to %s for %d running jobs", grace, len(in_flight))
    _, pending = await asyncio.wait(in_flight, timeout=grace.total_seconds())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
