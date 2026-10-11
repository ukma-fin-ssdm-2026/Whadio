import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, Final, Protocol
from uuid import UUID

from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..contracts.queues import (
    ALL_QUEUES,
    DEAD_LETTERS,
    NOTES_REQUESTS,
    PROCESSING_RESULTS,
    TRANSCRIPTION_REQUESTS,
    QueueSpec,
)
from ..contracts.results import ProcessingResult, parse_result
from ..contracts.transcription import TranscriptionRequested
from ..shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from .services import IJobPublisher, JobRequest

logger = logging.getLogger(__name__)

_RECONSUME_DELAY: Final = timedelta(seconds=1)


class IDelivery(Protocol):
    @property
    def body(self) -> bytes: ...

    @property
    def user_id(self) -> str | None: ...

    async def ack(self) -> None: ...

    async def reject(self, *, requeue: bool = False) -> None: ...


class IResultHandler(Protocol):
    """Each call runs in a transaction of its own and returns after the commit."""

    async def handle(self, result: ProcessingResult, /) -> list[JobRequest]: ...

    async def dead_lettered(self, job_id: UUID, /) -> None: ...


class IMessagePublisher(Protocol):
    async def publish(
        self, queue: str, body: bytes, /, *, message_type: str, correlation_id: str
    ) -> None: ...


class AmqpJobPublisher:
    def __init__(self, publisher: IMessagePublisher) -> None:
        self._publisher: IMessagePublisher = publisher

    async def publish(self, request: JobRequest) -> None:
        queue = (
            TRANSCRIPTION_REQUESTS
            if isinstance(request, TranscriptionRequested)
            else NOTES_REQUESTS
        )
        await self._publisher.publish(
            queue.name,
            request.model_dump_json().encode(),
            message_type=request.type,
            correlation_id=str(request.job_id),
        )


class _DeadLetter(BaseModel):
    # Any job message, request or result, names its job; the rest of it does not matter here.
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    job_id: UUID = Field(description="Processing job the dead-lettered message belongs to")


async def handle_delivery(
    delivery: IDelivery,
    handle: Callable[[ProcessingResult], Awaitable[list[JobRequest]]],
    publisher: IJobPublisher,
    publishers: Collection[str],
) -> None:
    """Leave a delivery whose handling raised unsettled, for the caller to return to the queue."""
    if delivery.user_id not in publishers:
        logger.warning(
            "Rejected a message on %s from an unexpected publisher", PROCESSING_RESULTS.name
        )
        await delivery.reject(requeue=False)
        return
    try:
        result = parse_result(delivery.body)
    except ValidationError as error:
        logger.warning(
            "Rejected a message from %s that is not a valid result (%d problems)",
            PROCESSING_RESULTS.name,
            error.error_count(),
        )
        await delivery.reject(requeue=False)
        return
    for request in await handle(result):
        await publisher.publish(request)
    await delivery.ack()


async def handle_dead_letter(
    delivery: IDelivery, fail: Callable[[UUID], Awaitable[None]], publishers: Collection[str]
) -> None:
    if delivery.user_id not in publishers:
        logger.warning("Dropped a dead letter from an unexpected publisher")
        await delivery.ack()
        return
    try:
        job_id = _DeadLetter.model_validate_json(delivery.body).job_id
    except ValidationError:
        logger.warning("Dropped a dead letter that names no job")
        await delivery.ack()
        return
    logger.warning("A message of job %s was dead-lettered; failing the job", job_id)
    await fail(job_id)
    await delivery.ack()


@dataclass(frozen=True, slots=True)
class ResultSource:
    publishers: Collection[str]
    """Broker users of the workers; a result from anyone else is rejected."""
    results: QueueSpec = PROCESSING_RESULTS
    dead_letters: QueueSpec = DEAD_LETTERS


async def serve_results(
    broker: BrokerSettings, handler: IResultHandler, source: ResultSource, stop: asyncio.Event
) -> None:
    async with await connect(broker, name="web") as connection:
        while not stop.is_set():
            failed = await _consume_until_a_failure(
                connection.channel, broker, handler, source, stop
            )
            # A nack on a quorum queue does not count towards its delivery limit; closing the
            # channel returns the unsettled message and counts it, so one that keeps failing is
            # dead-lettered.
            if failed and not stop.is_set():
                await asyncio.sleep(_RECONSUME_DELAY.total_seconds())


async def _consume_until_a_failure(
    open_channel: Callable[[], Awaitable[AbstractChannel]],
    broker: BrokerSettings,
    handler: IResultHandler,
    source: ResultSource,
    stop: asyncio.Event,
) -> bool:
    publishers, queues = source.publishers, source
    # Requests are dead-lettered from the web's own publications.
    senders = {*publishers, *([] if broker.user is None else [broker.user])}
    failed = asyncio.Event()
    async with await open_channel() as channel:
        await channel.set_qos(prefetch_count=1)
        for queue in (*ALL_QUEUES, queues.results, queues.dead_letters):
            await declare_queue(channel, queue.name, queue.arguments)
        publisher = AmqpJobPublisher(MessagePublisher(channel, broker.user))

        async def on_result(message: AbstractIncomingMessage) -> None:
            try:
                await handle_delivery(message, handler.handle, publisher, publishers)
            except Exception:
                logger.exception("Handling a result failed; returning it to the queue")
                failed.set()

        async def on_dead_letter(message: AbstractIncomingMessage) -> None:
            try:
                await handle_dead_letter(message, handler.dead_lettered, senders)
            except Exception:
                logger.exception("Handling a dead letter failed; returning it to the queue")
                failed.set()

        await (await channel.get_queue(queues.results.name)).consume(on_result)
        await (await channel.get_queue(queues.dead_letters.name)).consume(on_dead_letter)
        logger.info("Consuming %s and %s", queues.results.name, queues.dead_letters.name)
        waits = (asyncio.create_task(stop.wait()), asyncio.create_task(failed.wait()))
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        for wait in waits:
            wait.cancel()
    return failed.is_set()
