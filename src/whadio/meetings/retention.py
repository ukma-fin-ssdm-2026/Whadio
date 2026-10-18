from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.services import IRetentionAccess
from .enums import RecordingExpiryStatus
from .models import Meeting, RecordingDeletion
from .repositories import MeetingRepository

WARNING_PERIOD = timedelta(days=7)
BATCH_SIZE = 100


def recording_expiry_status(deadline: datetime, now: datetime) -> RecordingExpiryStatus:
    remaining = deadline - now
    if remaining <= timedelta(days=7):
        return RecordingExpiryStatus.EXPIRING_SOON
    return RecordingExpiryStatus.AVAILABLE


class NotificationUnavailableError(Exception):
    pass


class IRetentionNotifier(Protocol):
    async def enqueue(self, meeting_id: UUID, recipient_id: UUID, deadline: datetime) -> None:
        """Persist a deduplicated notice in the caller's transaction, without sending content."""
        ...


@dataclass(frozen=True)
class ExpiringRecording:
    meeting_id: UUID
    storage_key: str
    deadline: datetime
    warned_at: datetime | None
    recipients: list[UUID]


class IRetentionMeetings(Protocol):
    async def pending_deletions(self, after: UUID | None = None, /) -> list[UUID]: ...

    async def claim_deletion(self, deletion_id: UUID, /) -> str | None: ...

    async def complete_deletion(self, deletion_id: UUID, /) -> None: ...

    async def due(self, now: datetime, after: UUID | None = None, /) -> list[UUID]: ...

    async def claim(self, meeting_id: UUID, /) -> ExpiringRecording | None: ...

    async def mark_warned(self, meeting_id: UUID, now: datetime, /) -> None: ...

    async def mark_deleted(self, meeting_id: UUID, now: datetime, /) -> None: ...

    async def notify(self, recording: ExpiringRecording) -> None: ...


class IRetentionTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[IRetentionMeetings]: ...


class RetentionMeetings:
    def __init__(
        self, session: AsyncSession, policy: IRetentionAccess, notifications: IRetentionNotifier
    ) -> None:
        self._session: AsyncSession = session
        self._policy: IRetentionAccess = policy
        self._notifications: IRetentionNotifier = notifications

    async def pending_deletions(self, after: UUID | None = None) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(RecordingDeletion.deletion_id)
                .where(RecordingDeletion.deletion_id > after if after is not None else true())
                .order_by(RecordingDeletion.deletion_id)
                .limit(BATCH_SIZE)
            )
        )

    async def claim_deletion(self, deletion_id: UUID) -> str | None:
        return await self._session.scalar(
            select(RecordingDeletion.storage_key)
            .where(RecordingDeletion.deletion_id == deletion_id)
            .with_for_update(skip_locked=True)
        )

    async def complete_deletion(self, deletion_id: UUID) -> None:
        await self._session.execute(
            delete(RecordingDeletion).where(RecordingDeletion.deletion_id == deletion_id)
        )

    async def due(self, now: datetime, after: UUID | None = None) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(Meeting.meeting_id)
                .where(
                    Meeting.recording_deleted_at.is_(None),
                    Meeting.storage_path.is_not(None),
                    Meeting.recording_delete_after <= now + WARNING_PERIOD,
                    or_(
                        Meeting.recording_warning_sent_at.is_(None),
                        Meeting.recording_delete_after <= now,
                    ),
                )
                .where(Meeting.meeting_id > after if after is not None else true())
                .order_by(Meeting.meeting_id)
                .limit(BATCH_SIZE)
            )
        )

    async def claim(self, meeting_id: UUID) -> ExpiringRecording | None:
        meeting = await self._session.scalar(
            select(Meeting)
            .where(
                Meeting.meeting_id == meeting_id,
                Meeting.recording_deleted_at.is_(None),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if meeting is None or meeting.storage_path is None:
            return None
        scope = await MeetingRepository(self._session).scope(meeting_id)
        return ExpiringRecording(
            meeting_id,
            meeting.storage_path,
            meeting.recording_delete_after,
            meeting.recording_warning_sent_at,
            await self._policy.recipients(scope),
        )

    async def mark_warned(self, meeting_id: UUID, now: datetime) -> None:
        meeting = await MeetingRepository(self._session).get(meeting_id)
        meeting.recording_warning_sent_at = now
        await self._session.flush()

    async def mark_deleted(self, meeting_id: UUID, now: datetime) -> None:
        meeting = await MeetingRepository(self._session).get(meeting_id)
        meeting.recording_deleted_at = now
        meeting.storage_path = None
        await self._session.flush()

    async def notify(self, recording: ExpiringRecording) -> None:
        for recipient_id in recording.recipients:
            await self._notifications.enqueue(
                recording.meeting_id, recipient_id, recording.deadline
            )
