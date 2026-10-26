from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ..meetings.enums import RecordingExpiryStatus
from ..meetings.retention import (
    BATCH_SIZE,
    IRetentionTransactions,
    NotificationUnavailableError,
    recording_expiry_status,
)


class StorageUnavailableError(Exception):
    pass


class IRecordingStorage(Protocol):
    async def delete(self, key: str) -> None:
        """Delete one object; a missing object is a successful retry."""
        ...


@dataclass(frozen=True)
class RetentionResult:
    warned: list[UUID]
    deleted: list[UUID]
    failed: list[UUID]


class RetentionService:
    def __init__(self, transactions: IRetentionTransactions, storage: IRecordingStorage) -> None:
        self._transactions: IRetentionTransactions = transactions
        self._storage: IRecordingStorage = storage

    async def run(self, now: datetime) -> RetentionResult:
        # Reject naive input even when no recordings are due.
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Retention requires an aware timestamp")
        warned: list[UUID] = []
        deleted: list[UUID] = []
        failed: list[UUID] = []
        after = None
        while True:
            async with self._transactions.transaction() as meetings:
                due = await meetings.due(now, after)
            for meeting_id in due:
                try:
                    outcome = await self._expire(meeting_id, now)
                except (SQLAlchemyError, StorageUnavailableError, NotificationUnavailableError):
                    failed.append(meeting_id)
                else:
                    if outcome == "deleted":
                        deleted.append(meeting_id)
                    elif outcome == "warned":
                        warned.append(meeting_id)
            if len(due) < BATCH_SIZE:
                break
            after = due[-1]
        return RetentionResult(warned, deleted, failed)

    async def _expire(self, meeting_id: UUID, now: datetime) -> str:
        async with self._transactions.transaction() as meetings:
            recording = await meetings.claim(meeting_id)
            if recording is None:
                return "unchanged"
            status = recording_expiry_status(recording.deadline, now)
            if status == RecordingExpiryStatus.EXPIRED:
                await self._storage.delete(recording.storage_key)
                await meetings.mark_deleted(meeting_id, now)
                outcome = "deleted"
            elif status == RecordingExpiryStatus.EXPIRING_SOON and recording.warned_at is None:
                await meetings.notify(recording)
                await meetings.mark_warned(meeting_id, now)
                outcome = "warned"
            else:
                outcome = "unchanged"
        return outcome

    async def remove_deleted_meeting_recordings(self) -> list[UUID]:
        failed: list[UUID] = []
        after = None
        while True:
            async with self._transactions.transaction() as meetings:
                pending = await meetings.pending_deletions(after)
            for deletion_id in pending:
                try:
                    async with self._transactions.transaction() as meetings:
                        storage_key = await meetings.claim_deletion(deletion_id)
                        if storage_key is not None:
                            await self._storage.delete(storage_key)
                            await meetings.complete_deletion(deletion_id)
                except (SQLAlchemyError, StorageUnavailableError):
                    failed.append(deletion_id)
            if len(pending) < BATCH_SIZE:
                break
            after = pending[-1]
        return failed
