import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from conftest import NOW

from ..meetings.retention import (
    BATCH_SIZE,
    ExpiringRecording,
    IRetentionMeetings,
    NotificationUnavailableError,
)
from .services import RetentionService, StorageUnavailableError


class RecordingStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.fail: bool = False
        self.after_delete: Callable[[], None] | None = None

    async def delete(self, key: str) -> None:
        if self.fail:
            raise StorageUnavailableError
        self.deleted.append(key)
        if self.after_delete is not None:
            self.after_delete()


class Transactions:
    def __init__(self, recording: ExpiringRecording) -> None:
        self.recording: ExpiringRecording | None = recording
        self.notices: list[UUID] = []
        self.fail_notification: bool = False
        self.fail_commit: bool = False

    async def pending_deletions(self, _after: UUID | None = None) -> list[UUID]:
        return []

    async def claim_deletion(self, _deletion_id: UUID) -> str | None:
        return None

    async def complete_deletion(self, _deletion_id: UUID) -> None:
        pass

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
        previous, notices = self.recording, self.notices.copy()
        try:
            yield self
            self._commit()
        except (OperationalError, StorageUnavailableError, NotificationUnavailableError):
            self.recording, self.notices = previous, notices
            raise

    def _commit(self) -> None:
        if self.fail_commit:
            self.fail_commit = False
            raise OperationalError(None, None, RuntimeError("commit failed"))

    def fail_next_commit(self) -> None:
        self.fail_commit = True

    async def due(self, _now: datetime, _after: UUID | None = None) -> list[UUID]:
        return [] if self.recording is None else [self.recording.meeting_id]

    async def claim(self, _meeting_id: UUID) -> ExpiringRecording | None:
        return self.recording

    async def mark_warned(self, _meeting_id: UUID, now: datetime) -> None:
        if self.recording is not None:
            self.recording = replace(self.recording, warned_at=now)

    async def mark_deleted(self, _meeting_id: UUID, _now: datetime) -> None:
        self.recording = None

    async def notify(self, recording: ExpiringRecording) -> None:
        for recipient in recording.recipients:
            self.notices.append(recipient)
            if self.fail_notification:
                raise NotificationUnavailableError


@pytest.mark.parametrize(
    ("offset", "warned", "deleted"),
    [
        (timedelta(days=7, microseconds=1), False, False),
        (timedelta(days=7), True, False),
        (timedelta(microseconds=1), True, False),
        (timedelta(), False, True),
        (timedelta(days=-1), False, True),
    ],
)
def test_retention_warning_and_deletion_boundaries(
    offset: timedelta, *, warned: bool, deleted: bool
) -> None:
    # Arrange
    now, meeting_id = datetime.now(UTC), uuid4()
    transactions = Transactions(
        ExpiringRecording(meeting_id, "test", now + offset, None, [uuid4()])
    )
    service = RetentionService(transactions, RecordingStore())
    # Act
    result = asyncio.run(service.run(now))
    # Assert
    assert (bool(result.warned), bool(result.deleted), result.failed) == (warned, deleted, [])


def test_warning_is_not_repeated_on_retry() -> None:
    # Arrange
    now = datetime.now(UTC)
    transactions = Transactions(
        ExpiringRecording(uuid4(), "test", now + timedelta(days=7), None, [uuid4()])
    )
    service = RetentionService(transactions, RecordingStore())
    # Act
    asyncio.run(service.run(now))
    asyncio.run(service.run(now))
    # Assert
    assert len(transactions.notices) == 1


def test_notification_failure_rolls_back_warning_and_retries() -> None:
    # Arrange
    now = datetime.now(UTC)
    transactions = Transactions(
        ExpiringRecording(uuid4(), "test", now + timedelta(days=7), None, [uuid4()])
    )
    transactions.fail_notification = True
    service = RetentionService(transactions, RecordingStore())
    # Act
    failed = asyncio.run(service.run(now))
    transactions.fail_notification = False
    retried = asyncio.run(service.run(now))
    # Assert
    assert (len(failed.failed), len(retried.warned), len(transactions.notices)) == (1, 1, 1)


def test_storage_failure_preserves_recording_for_retry() -> None:
    # Arrange
    now, meeting_id = datetime.now(UTC), uuid4()
    transactions = Transactions(ExpiringRecording(meeting_id, "test", now, None, []))
    storage = RecordingStore()
    storage.fail = True
    service = RetentionService(transactions, storage)
    # Act
    failed = asyncio.run(service.run(now))
    storage.fail = False
    retried = asyncio.run(service.run(now))
    # Assert
    assert (failed.failed, retried.deleted, transactions.recording) == (
        [meeting_id],
        [meeting_id],
        None,
    )


def test_storage_delete_can_be_repeated_after_database_commit_failure() -> None:
    # Arrange
    now, meeting_id = datetime.now(UTC), uuid4()
    transactions = Transactions(ExpiringRecording(meeting_id, "test", now, None, []))
    storage = RecordingStore()
    service = RetentionService(transactions, storage)

    async def scenario() -> tuple[list[UUID], list[UUID]]:
        storage.after_delete = transactions.fail_next_commit
        failed = await service.run(now)
        storage.after_delete = None
        retried = await service.run(now)
        return failed.failed, retried.deleted

    # Act
    result = asyncio.run(scenario())
    # Assert
    assert (result, storage.deleted) == (([meeting_id], [meeting_id]), ["test", "test"])


class PagedMeetings:
    def __init__(self, count: int) -> None:
        self.ids: list[UUID] = sorted(uuid4() for _ in range(count))
        self.due_queries: int = 0
        self.pending_queries: int = 0
        self.completed: list[UUID] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
        yield self

    def _page_after(self, after: UUID | None) -> list[UUID]:
        return [i for i in self.ids if after is None or i > after][:BATCH_SIZE]

    async def due(self, _now: datetime, after: UUID | None = None) -> list[UUID]:
        self.due_queries += 1
        return self._page_after(after)

    async def pending_deletions(self, after: UUID | None = None) -> list[UUID]:
        self.pending_queries += 1
        return self._page_after(after)

    async def claim_deletion(self, deletion_id: UUID) -> str | None:
        return str(deletion_id)

    async def complete_deletion(self, deletion_id: UUID) -> None:
        self.completed.append(deletion_id)

    async def claim(self, meeting_id: UUID) -> ExpiringRecording | None:
        return ExpiringRecording(meeting_id, str(meeting_id), NOW, None, [])

    async def mark_warned(self, _meeting_id: UUID, _now: datetime) -> None:
        pass

    async def mark_deleted(self, _meeting_id: UUID, _now: datetime) -> None:
        pass

    async def notify(self, recording: ExpiringRecording) -> None:
        del recording


_DUE_COUNTS = [
    pytest.param(BATCH_SIZE - 1, id="bva-below-batch-size"),
    pytest.param(BATCH_SIZE, id="bva-on-batch-size"),
    pytest.param(BATCH_SIZE + 1, id="bva-above-batch-size"),
]
_PAGE_QUERIES = [
    pytest.param(BATCH_SIZE - 1, 1, id="bva-below-batch-size"),
    pytest.param(BATCH_SIZE, 2, id="bva-on-batch-size"),
    pytest.param(BATCH_SIZE + 1, 2, id="bva-above-batch-size"),
]


@pytest.mark.parametrize("count", _DUE_COUNTS)
def test_retention_pass_deletes_every_due_recording_once_across_pages(count: int) -> None:
    # Arrange
    meetings = PagedMeetings(count)
    service = RetentionService(meetings, RecordingStore())

    # Act
    result = asyncio.run(service.run(NOW))

    # Assert
    assert result.deleted == meetings.ids


@pytest.mark.parametrize(("count", "queries"), _PAGE_QUERIES)
def test_retention_pass_asks_for_another_page_only_after_a_full_one(
    count: int, queries: int
) -> None:
    # Arrange
    meetings = PagedMeetings(count)
    service = RetentionService(meetings, RecordingStore())

    # Act
    asyncio.run(service.run(NOW))

    # Assert
    assert meetings.due_queries == queries


@pytest.mark.parametrize("count", _DUE_COUNTS)
def test_cleanup_removes_every_pending_recording_once_across_pages(count: int) -> None:
    # Arrange
    meetings = PagedMeetings(count)
    service = RetentionService(meetings, RecordingStore())

    # Act
    asyncio.run(service.remove_deleted_meeting_recordings())

    # Assert
    assert meetings.completed == meetings.ids


@pytest.mark.parametrize(("count", "queries"), _PAGE_QUERIES)
def test_cleanup_asks_for_another_page_only_after_a_full_one(count: int, queries: int) -> None:
    # Arrange
    meetings = PagedMeetings(count)
    service = RetentionService(meetings, RecordingStore())

    # Act
    asyncio.run(service.remove_deleted_meeting_recordings())

    # Assert
    assert meetings.pending_queries == queries
