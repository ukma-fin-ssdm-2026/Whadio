import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.repositories import WorkspaceSettingsRepository
from ..contracts.queues import (
    ALL_QUEUES,
    NOTES_REQUESTS,
    PROCESSING_RESULTS,
    TRANSCRIPTION_REQUESTS,
)
from ..contracts.results import ProcessingResult, parse_result
from ..contracts.transcription import TranscriptionRequested
from ..meetings.repositories import MeetingPipelineRepository
from ..shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ..shared.database import Database
from ..shared.storage import IObjectStorage
from .repositories import JobRepository
from .services import IJobPublisher, JobRequest, ProcessingService

logger = logging.getLogger(__name__)


class IDelivery(Protocol):
    @property
    def body(self) -> bytes: ...

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool = True) -> None: ...

    async def reject(self, *, requeue: bool = False) -> None: ...


class AmqpJobPublisher:
    def __init__(self, publisher: MessagePublisher) -> None:
        self._publisher: MessagePublisher = publisher

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


def processing_service(session: AsyncSession, storage: IObjectStorage) -> ProcessingService:
    return ProcessingService(
        JobRepository(session),
        MeetingPipelineRepository(session),
        WorkspaceSettingsRepository(session),
        storage,
    )


async def handle_delivery(
    delivery: IDelivery,
    handle: Callable[[ProcessingResult], Awaitable[list[JobRequest]]],
    publisher: IJobPublisher,
) -> None:
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
    try:
        requests = await handle(result)
        for request in requests:
            await publisher.publish(request)
    except Exception:
        # Requeued, the delivery counts towards the queue's limit, so a result that keeps failing
        # ends up dead-lettered instead of blocking the queue.
        logger.exception("Handling a result of job %s failed", result.job_id)
        await delivery.nack(requeue=True)
        return
    await delivery.ack()


async def serve_results(
    broker: BrokerSettings, database: Database, storage: IObjectStorage, stop: asyncio.Event
) -> None:
    connection = await connect(broker, name="web")
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        for queue in ALL_QUEUES:
            await declare_queue(channel, queue.name, queue.arguments)
        results = await channel.get_queue(PROCESSING_RESULTS.name)
        publisher = AmqpJobPublisher(MessagePublisher(channel, broker.user))

        async def handle(result: ProcessingResult) -> list[JobRequest]:
            async with database.transaction() as session:
                return await processing_service(session, storage).handle(result)

        async def on_message(message: AbstractIncomingMessage) -> None:
            await handle_delivery(message, handle, publisher)

        tag = await results.consume(on_message)
        logger.info("Consuming %s", PROCESSING_RESULTS.name)
        await stop.wait()
        await results.cancel(tag)
