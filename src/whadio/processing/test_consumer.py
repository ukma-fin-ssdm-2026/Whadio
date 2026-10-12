import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.repositories import MembershipRepository, WorkspaceSettingsRepository
from ..accounts.services import WorkspaceMembershipService, WorkspaceSettingsService
from ..audit.services import AuditWriter
from ..contracts.common import JobKind, Transcript
from ..contracts.notes import MeetingBrief, NotesPreset, NotesRequested
from ..contracts.queues import PROCESSING_RESULTS, QueueSpec
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
)
from ..meetings.contracts import EvictionNotice
from ..meetings.enums import ProcessingState
from ..meetings.models import Meeting
from ..meetings.persistence import MeetingPersistence, PersistenceDependencies
from ..meetings.repositories import MeetingRepository
from ..meetings.services import MeetingService
from ..shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ..shared.storage import PresignedUrl
from .consumer import (
    AmqpJobPublisher,
    ProcessingTransactions,
    ResultSource,
    WorkerUsers,
    handle_dead_letter,
    handle_delivery,
    serve_publishing,
    serve_results,
)
from .enums import JobType
from .repositories import JobRepository
from .services import JobRequest, ProcessingService

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
WORKER = "whadio-asr"
WORKERS = WorkerUsers(transcription=WORKER, notes="whadio-notes")


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

    async def handle(self, result: ProcessingResult) -> None:
        await self.handled.put(result.job_id)

    async def dead_lettered(self, job_id: UUID) -> None:
        await self.handled.put(job_id)


class _StackSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    broker: BrokerSettings = Field(description="Connection to the Compose stack's RabbitMQ")


def started_body(kind: JobKind = JobKind.TRANSCRIPTION) -> bytes:
    return (
        JobStarted(job_id=uuid4(), meeting_id=uuid4(), kind=kind, started_at=NOW)
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


async def accept(_result: ProcessingResult) -> None:
    pass


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
                    broker,
                    handler,
                    ResultSource(
                        WorkerUsers(broker.user or "", broker.user or ""), results, dead_letters
                    ),
                    stop,
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
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_result_from_an_unexpected_publisher_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(), user_id="someone-else")
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_result_without_a_publisher_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(), user_id=None)
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_handled_result_is_acknowledged() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "ack"


def test_notes_start_from_the_notes_worker_is_acknowledged() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(JobKind.NOTES), user_id=WORKERS.notes)
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "ack"


def test_notes_start_from_the_asr_worker_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(started_body(JobKind.NOTES), user_id=WORKERS.transcription)
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_transcription_result_from_the_notes_worker_is_rejected_without_requeue() -> None:
    # Arrange
    failed = TranscriptionFailed(
        job_id=uuid4(),
        meeting_id=uuid4(),
        finished_at=NOW,
        reason=TranscriptionFailure.UNSUPPORTED_AUDIO,
    )
    delivery = FakeDelivery(failed.model_dump_json().encode(), user_id=WORKERS.notes)
    # Act
    asyncio.run(handle_delivery(delivery, accept, WORKERS))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_result_whose_handling_fails_is_left_unsettled() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())

    async def handle(_result: ProcessingResult) -> None:
        raise RuntimeError("database unavailable")

    # Act
    with pytest.raises(RuntimeError):
        asyncio.run(handle_delivery(delivery, handle, WORKERS))
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


# --- Transactions ---


class SavepointTransactions:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._session.begin_nested():
            yield self._session


def processing_service(session: AsyncSession) -> ProcessingService:
    memberships = WorkspaceMembershipService(MembershipRepository(session))
    meetings = MeetingService(
        MeetingRepository(session),
        AccessPolicy(AccessRepository(session), memberships),
        AuditWriter(session),
    )
    return ProcessingService(
        JobRepository(session),
        meetings,
        MeetingPersistence(
            PersistenceDependencies(
                meetings,
                MeetingRepository(session),
                memberships,
                AuditWriter(session),
                AccessPolicy(AccessRepository(session), memberships),
                UnavailableEvictions(),
            )
        ),
        WorkspaceSettingsService(WorkspaceSettingsRepository(session)),
        SigningStorage(),
    )


class UnavailableEvictions:
    async def enqueue(self, notice: EvictionNotice) -> None:
        del notice
        raise AssertionError


class SigningStorage:
    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        del key, data, content_type
        raise AssertionError

    def delete(self, key: str) -> None:
        del key
        raise AssertionError

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        return PresignedUrl(f"http://storage.test/{key}", NOW + expires_in)


def transactions(session: AsyncSession, publisher: FakePublisher) -> ProcessingTransactions:
    return ProcessingTransactions(
        SavepointTransactions(session), processing_service, publisher, asyncio.Event()
    )


async def queued_job(session: AsyncSession) -> tuple[UUID, UUID]:
    meeting_id = await AsyncDatabase.add_meeting(
        session, await AsyncDatabase.add_workspace(session)
    )
    return meeting_id, await JobRepository(session).add(meeting_id, JobType.TRANSCRIPTION)


@pytest.mark.slow
def test_handled_result_changes_the_database(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> ProcessingState | None:
        meeting_id, job_id = await queued_job(session)
        # Act
        await transactions(session, FakePublisher()).handle(
            JobStarted(
                job_id=job_id, meeting_id=meeting_id, kind=JobKind.TRANSCRIPTION, started_at=NOW
            )
        )
        return await session.scalar(
            select(Meeting.processing_state).where(Meeting.meeting_id == meeting_id)
        )

    state = async_database.run(scenario)
    # Assert
    assert state is ProcessingState.PROCESSING


@pytest.mark.slow
def test_queued_job_is_published_once(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        _, job_id = await queued_job(session)
        publisher = FakePublisher()
        publishing = transactions(session, publisher)
        # Act
        while await publishing.publish_next():
            pass
        await publishing.publish_next()
        return [request.job_id for request in publisher.published].count(job_id)

    published = async_database.run(scenario)
    # Assert
    assert published == 1


# --- Publishing rounds ---


class FakePublishing:
    def __init__(self, failures: int = 0) -> None:
        self.waiting: int = 1
        self.published: asyncio.Event = asyncio.Event()
        self._failures: int = failures

    async def publish_next(self) -> bool:
        if self._failures:
            self._failures -= 1
            raise ConnectionError
        if not self.waiting:
            return False
        self.waiting -= 1
        self.published.set()
        return True


async def serve_until_published(
    publishing: FakePublishing, interval: timedelta, *, wake: bool
) -> bool:
    queued, stop = asyncio.Event(), asyncio.Event()
    serving = asyncio.create_task(serve_publishing(publishing, queued, stop, interval))
    if wake:
        queued.set()
    try:
        async with asyncio.timeout(5):
            await publishing.published.wait()
        return True
    finally:
        stop.set()
        await serving


def test_queued_jobs_are_published_at_once_when_woken() -> None:
    # Arrange
    publishing = FakePublishing()
    # Act
    published = asyncio.run(serve_until_published(publishing, timedelta(hours=1), wake=True))
    # Assert
    assert published


def test_job_whose_publish_failed_is_published_on_a_later_round() -> None:
    # Arrange
    publishing = FakePublishing(failures=1)
    # Act
    published = asyncio.run(
        serve_until_published(publishing, timedelta(milliseconds=10), wake=False)
    )
    # Assert
    assert published
