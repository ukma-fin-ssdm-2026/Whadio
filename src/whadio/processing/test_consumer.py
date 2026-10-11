import asyncio
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..contracts.common import JobKind, Transcript
from ..contracts.notes import MeetingBrief, NotesPreset, NotesRequested
from ..contracts.queues import PROCESSING_RESULTS, QueueSpec
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import AudioLink, TranscriptionRequested
from ..shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from .consumer import (
    AmqpJobPublisher,
    ResultSource,
    handle_dead_letter,
    handle_delivery,
    serve_results,
)
from .services import JobRequest

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
WORKER = "whadio-asr"


class FakeDelivery:
    def __init__(self, body: bytes, user_id: str | None = WORKER) -> None:
        self._body: bytes = body
        self._user_id: str | None = user_id
        self.outcome: str = "unsettled"

    @property
    def body(self) -> bytes:
        return self._body

    @property
    def user_id(self) -> str | None:
        return self._user_id

    async def ack(self) -> None:
        self.outcome = "ack"

    async def reject(self, *, requeue: bool = False) -> None:
        self.outcome = f"reject requeue={requeue}"


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[JobRequest] = []

    async def publish(self, request: JobRequest) -> None:
        self.published.append(request)


class FakeMessagePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    async def publish(
        self, queue: str, _body: bytes, *, message_type: str, correlation_id: str
    ) -> None:
        self.messages.append((queue, message_type, correlation_id))


class RecordingHandler:
    def __init__(self) -> None:
        self.handled: asyncio.Queue[UUID] = asyncio.Queue()

    async def handle(self, result: ProcessingResult) -> list[JobRequest]:
        await self.handled.put(result.job_id)
        return []

    async def dead_lettered(self, job_id: UUID) -> None:
        await self.handled.put(job_id)


class _StackSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    broker: BrokerSettings = Field(description="Connection to the Compose stack's RabbitMQ")


def started_body() -> bytes:
    return (
        JobStarted(job_id=uuid4(), meeting_id=uuid4(), kind=JobKind.NOTES, started_at=NOW)
        .model_dump_json()
        .encode()
    )


def transcription_request(job_id: UUID) -> TranscriptionRequested:
    return TranscriptionRequested(
        job_id=job_id,
        meeting_id=uuid4(),
        audio=AudioLink.model_validate(
            {"url": "http://storage.test/recording", "expires_at": NOW}, strict=False
        ),
        language=None,
        glossary=(),
    )


def notes_request() -> NotesRequested:
    return NotesRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        preset=NotesPreset.SUMMARY,
        meeting=MeetingBrief(name=None, recorded_at=NOW),
        transcript=Transcript(language="uk", speakers=(), segments=()),
        context=(),
        glossary=(),
    )


async def no_follow_ups(_result: ProcessingResult) -> list[JobRequest]:
    return []


async def publish_amqp(request: JobRequest) -> list[str]:
    publisher = FakeMessagePublisher()
    await AmqpJobPublisher(publisher).publish(request)
    return [queue for queue, _, _ in publisher.messages]


async def _serve_one_result(broker: BrokerSettings) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    results = QueueSpec(f"test.results.{suffix}", PROCESSING_RESULTS.arguments)
    dead_letters = QueueSpec(f"test.dead-letters.{suffix}", {"x-queue-type": "quorum"})
    handler = RecordingHandler()
    stop = asyncio.Event()
    job_id = uuid4()
    async with await connect(broker, name="consumer-test") as connection:
        channel = await connection.channel()
        queue = await declare_queue(channel, results.name, results.arguments)
        try:
            body = (
                JobStarted(job_id=job_id, meeting_id=uuid4(), kind=JobKind.NOTES, started_at=NOW)
                .model_dump_json()
                .encode()
            )
            await MessagePublisher(channel, broker.user).publish(
                results.name, body, message_type="job_started", correlation_id=str(job_id)
            )
            consumer = asyncio.create_task(
                serve_results(
                    broker, handler, ResultSource({broker.user or ""}, results, dead_letters), stop
                )
            )
            async with asyncio.timeout(30):
                handled = await handler.handled.get()
            stop.set()
            await consumer
        finally:
            await queue.delete(if_unused=False, if_empty=False)
            dead = await channel.get_queue(dead_letters.name)
            await dead.delete(if_unused=False, if_empty=False)
    return job_id, handled


# --- Results ---


def test_message_that_is_not_a_result_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(b'{"type": "unknown"}')
    # Act
    asyncio.run(handle_delivery(delivery, no_follow_ups, FakePublisher(), {WORKER}))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_result_from_an_unexpected_publisher_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(), user_id="someone-else")
    # Act
    asyncio.run(handle_delivery(delivery, no_follow_ups, FakePublisher(), {WORKER}))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_result_without_a_publisher_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(), user_id=None)
    # Act
    asyncio.run(handle_delivery(delivery, no_follow_ups, FakePublisher(), {WORKER}))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_handled_result_is_acknowledged() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())
    # Act
    asyncio.run(handle_delivery(delivery, no_follow_ups, FakePublisher(), {WORKER}))
    # Assert
    assert delivery.outcome == "ack"


def test_follow_up_jobs_are_published() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())
    publisher = FakePublisher()

    async def handle(result: ProcessingResult) -> list[JobRequest]:
        return [transcription_request(result.job_id)]

    # Act
    asyncio.run(handle_delivery(delivery, handle, publisher, {WORKER}))
    # Assert
    assert [request.type for request in publisher.published] == ["transcription_requested"]


def test_result_whose_handling_fails_is_left_unsettled() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())

    async def handle(_result: ProcessingResult) -> list[JobRequest]:
        raise RuntimeError("database unavailable")

    # Act
    with pytest.raises(RuntimeError):
        asyncio.run(handle_delivery(delivery, handle, FakePublisher(), {WORKER}))
    # Assert
    assert delivery.outcome == "unsettled"


# --- Dead letters ---


def test_dead_lettered_request_fails_its_job() -> None:
    # Arrange
    job_id = uuid4()
    delivery = FakeDelivery(transcription_request(job_id).model_dump_json().encode(), "web")
    failed: list[UUID] = []

    async def fail(dead_job_id: UUID) -> None:
        failed.append(dead_job_id)

    # Act
    asyncio.run(handle_dead_letter(delivery, fail, {"web"}))
    # Assert
    assert failed == [job_id]


def test_dead_letter_that_names_no_job_is_dropped() -> None:
    # Arrange
    delivery = FakeDelivery(b'{"type": "unknown"}', "web")

    async def fail(_job_id: UUID) -> None:
        raise AssertionError("no job to fail")

    # Act
    asyncio.run(handle_dead_letter(delivery, fail, {"web"}))
    # Assert
    assert delivery.outcome == "ack"


def test_dead_letter_from_an_unexpected_publisher_fails_no_job() -> None:
    # Arrange
    delivery = FakeDelivery(transcription_request(uuid4()).model_dump_json().encode(), "intruder")
    failed: list[UUID] = []

    async def fail(dead_job_id: UUID) -> None:
        failed.append(dead_job_id)

    # Act
    asyncio.run(handle_dead_letter(delivery, fail, {"web"}))
    # Assert
    assert failed == []


# --- Publishing ---


def test_transcription_request_goes_to_the_transcription_queue() -> None:
    # Arrange
    request = transcription_request(uuid4())
    # Act
    queues = asyncio.run(publish_amqp(request))
    # Assert
    assert queues == ["transcription.requests"]


def test_notes_request_goes_to_the_notes_queue() -> None:
    # Arrange
    request = notes_request()
    # Act
    queues = asyncio.run(publish_amqp(request))
    # Assert
    assert queues == ["notes.requests"]


# --- Serving ---


@pytest.mark.slow
def test_served_result_reaches_the_handler() -> None:
    # Arrange
    broker = _StackSettings.model_validate({}).broker
    # Act
    published, handled = asyncio.run(_serve_one_result(broker))
    # Assert
    assert handled == published
