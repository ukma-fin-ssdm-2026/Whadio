import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from ..contracts.common import JobKind
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import AudioLink, TranscriptionRequested
from .consumer import handle_delivery
from .services import JobRequest

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


class FakeDelivery:
    def __init__(self, body: bytes) -> None:
        self._body: bytes = body
        self.outcome: str = "unsettled"

    @property
    def body(self) -> bytes:
        return self._body

    async def ack(self) -> None:
        self.outcome = "ack"

    async def nack(self, *, requeue: bool = True) -> None:
        self.outcome = f"nack requeue={requeue}"

    async def reject(self, *, requeue: bool = False) -> None:
        self.outcome = f"reject requeue={requeue}"


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[JobRequest] = []

    async def publish(self, request: JobRequest) -> None:
        self.published.append(request)


def started_body() -> bytes:
    return (
        JobStarted(job_id=uuid4(), meeting_id=uuid4(), kind=JobKind.NOTES, started_at=NOW)
        .model_dump_json()
        .encode()
    )


def follow_up(result: ProcessingResult) -> TranscriptionRequested:
    return TranscriptionRequested(
        job_id=result.job_id,
        meeting_id=result.meeting_id,
        audio=AudioLink.model_validate(
            {"url": "http://storage.test/recording", "expires_at": NOW}, strict=False
        ),
        language=None,
        glossary=(),
    )


def test_message_that_is_not_a_result_is_rejected_without_requeue() -> None:
    # Arrange
    delivery = FakeDelivery(b'{"type": "unknown"}')

    async def handle(_result: ProcessingResult) -> list[JobRequest]:
        return []

    # Act
    asyncio.run(handle_delivery(delivery, handle, FakePublisher()))
    # Assert
    assert delivery.outcome == "reject requeue=False"


def test_handled_result_is_acknowledged() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())

    async def handle(_result: ProcessingResult) -> list[JobRequest]:
        return []

    # Act
    asyncio.run(handle_delivery(delivery, handle, FakePublisher()))
    # Assert
    assert delivery.outcome == "ack"


def test_follow_up_jobs_are_published() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())
    publisher = FakePublisher()

    async def handle(result: ProcessingResult) -> list[JobRequest]:
        return [follow_up(result)]

    # Act
    asyncio.run(handle_delivery(delivery, handle, publisher))
    # Assert
    assert [request.type for request in publisher.published] == ["transcription_requested"]


def test_result_whose_handling_fails_is_requeued() -> None:
    # Arrange
    delivery = FakeDelivery(started_body())

    async def handle(_result: ProcessingResult) -> list[JobRequest]:
        raise RuntimeError("database unavailable")

    # Act
    asyncio.run(handle_delivery(delivery, handle, FakePublisher()))
    # Assert
    assert delivery.outcome == "nack requeue=True"
