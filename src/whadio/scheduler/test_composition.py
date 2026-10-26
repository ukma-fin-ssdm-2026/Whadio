import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..accounts.contracts import UserProfile
from ..meetings.models import Meeting
from ..notifications.fakes import InMemoryNotificationOutbox
from ..notifications.models import NotificationOutbox
from ..notifications.services import NotificationDrainer, Recipient
from ..notifications.settings import NotificationSettings, SmtpSettings
from ..notifications.templates import NoticeKind, RecordingDeletionWarning
from ..retention.services import RetentionService
from .composition import (
    AccountRecipients,
    OutboxRetentionNotices,
    RetentionTransactions,
    notification_drainer,
)

DEADLINE = datetime(2026, 5, 4, 9, 30, tzinfo=UTC)


class UnusedDatabase:
    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        raise AssertionError("composing the drainer opens no transaction")


class Profiles:
    def __init__(self, profiles: dict[UUID, UserProfile]) -> None:
        self._profiles: dict[UUID, UserProfile] = profiles

    async def profile(self, user_id: UUID) -> UserProfile | None:
        return self._profiles.get(user_id)


def settings(smtp: SmtpSettings | None) -> NotificationSettings:
    return NotificationSettings(smtp=smtp, public_url=HttpUrl("https://whadio.example.com"))


def test_scheduler_without_a_relay_has_no_drainer() -> None:
    # Act
    drainer = notification_drainer(settings(None), UnusedDatabase())
    # Assert
    assert drainer is None


def test_scheduler_with_a_relay_drains_the_outbox() -> None:
    # Arrange
    relay = SmtpSettings(host="127.0.0.1", port=1025, starttls=False, from_address="w@localhost")
    # Act
    drainer = notification_drainer(settings(relay), UnusedDatabase())
    # Assert
    assert isinstance(drainer, NotificationDrainer)


def test_recipient_is_the_name_and_email_of_the_account() -> None:
    # Arrange
    user_id = uuid4()
    recipients = AccountRecipients(
        Profiles({user_id: UserProfile("Olena Koval", "olena@example.com")})
    )
    # Act
    found = asyncio.run(recipients.recipient(user_id))
    # Assert
    assert found == Recipient("Olena Koval", "olena@example.com")


def test_recipient_without_an_account_is_missing() -> None:
    # Arrange
    recipients = AccountRecipients(Profiles({}))
    # Act
    found = asyncio.run(recipients.recipient(uuid4()))
    # Assert
    assert found is None


class MeetingRecords:
    def __init__(self, *meetings: Meeting) -> None:
        self._meetings: dict[UUID, Meeting] = {meeting.meeting_id: meeting for meeting in meetings}

    async def get(self, meeting_id: UUID) -> Meeting:
        return self._meetings[meeting_id]


def test_retention_warning_names_the_meeting_and_its_deadline() -> None:
    # Arrange
    meeting, recipient = Meeting(meeting_id=uuid4(), name="Planning"), uuid4()
    outbox = InMemoryNotificationOutbox(lambda: datetime.now(UTC))
    notices = OutboxRetentionNotices(outbox, MeetingRecords(meeting))
    # Act
    asyncio.run(notices.enqueue(meeting.meeting_id, recipient, DEADLINE))
    # Assert
    assert [
        (stored.recipient_id, stored.dedupe_key, stored.kind, stored.payload)
        for stored in outbox.notices.values()
    ] == [
        (
            recipient,
            f"recording_deletion_warning:{meeting.meeting_id}:{recipient}",
            NoticeKind.RECORDING_DELETION_WARNING,
            {
                "meeting_id": str(meeting.meeting_id),
                "meeting_name": "Planning",
                "deletes_at": "2026-05-04T09:30:00Z",
            },
        )
    ]


def test_repeated_retention_warning_is_reserved_once() -> None:
    # Arrange
    meeting, recipient = Meeting(meeting_id=uuid4(), name="Planning"), uuid4()
    outbox = InMemoryNotificationOutbox(lambda: datetime.now(UTC))
    notices = OutboxRetentionNotices(outbox, MeetingRecords(meeting))
    asyncio.run(notices.enqueue(meeting.meeting_id, recipient, DEADLINE))
    # Act
    asyncio.run(notices.enqueue(meeting.meeting_id, recipient, DEADLINE + timedelta(days=1)))
    # Assert
    assert len(outbox.notices) == 1


class SavepointTransactions:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._session.begin_nested():
            yield self._session


class KeptRecordings:
    async def delete(self, key: str) -> None:
        del key


async def expiring_meeting(session: AsyncSession, now: datetime) -> tuple[UUID, UUID]:
    """The workspace owner, and a meeting of theirs whose recording is deleted in three days."""
    place = await AsyncDatabase.add_workspace(session)
    meeting_id = await AsyncDatabase.add_meeting(session, place)
    meeting = await session.get_one(Meeting, meeting_id)
    meeting.recording_delete_after = now + timedelta(days=3)
    await session.flush()
    return place[0], meeting_id


type Warnings = list[tuple[str, RecordingDeletionWarning]]


async def warnings_for(session: AsyncSession, recipient: UUID) -> Warnings:
    rows = await session.execute(
        select(NotificationOutbox.dedupe_key, NotificationOutbox.payload).where(
            NotificationOutbox.recipient_user_id == recipient,
            NotificationOutbox.kind == NoticeKind.RECORDING_DELETION_WARNING,
        )
    )
    return [(key, RecordingDeletionWarning.model_validate(payload)) for key, payload in rows]


@pytest.mark.slow
def test_retention_reserves_a_warning_for_an_expiring_recording(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    now = datetime.now(UTC)

    async def scenario(session: AsyncSession) -> tuple[Warnings, Warnings]:
        owner, meeting_id = await expiring_meeting(session, now)
        retention = RetentionService(
            RetentionTransactions(SavepointTransactions(session)), KeptRecordings()
        )
        # Act
        await retention.run(now)
        expected = RecordingDeletionWarning(
            meeting_id=meeting_id, meeting_name="Planning", deletes_at=now + timedelta(days=3)
        )
        return await warnings_for(session, owner), [
            (f"recording_deletion_warning:{meeting_id}:{owner}", expected)
        ]

    warnings, expected = async_database.run(scenario)
    # Assert
    assert warnings == expected


@pytest.mark.slow
def test_failed_retention_transaction_rolls_back_its_warning(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    now = datetime.now(UTC)

    async def scenario(session: AsyncSession) -> Warnings:
        owner, meeting_id = await expiring_meeting(session, now)
        transactions = RetentionTransactions(SavepointTransactions(session))

        # Act
        async def warn() -> None:
            async with transactions.transaction() as meetings:
                recording = await meetings.claim(meeting_id)
                if recording is None:
                    raise LookupError(meeting_id)
                await meetings.notify(recording)
                raise RuntimeError

        with pytest.raises(RuntimeError):
            await warn()
        return await warnings_for(session, owner)

    warnings = async_database.run(scenario)
    # Assert
    assert warnings == []


@pytest.mark.slow
def test_warned_recording_is_not_warned_again_after_its_notice_is_removed(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    now = datetime.now(UTC)

    async def scenario(session: AsyncSession) -> Warnings:
        owner, _ = await expiring_meeting(session, now)
        retention = RetentionService(
            RetentionTransactions(SavepointTransactions(session)), KeptRecordings()
        )
        await retention.run(now)
        await session.execute(
            delete(NotificationOutbox).where(NotificationOutbox.recipient_user_id == owner)
        )
        # Act
        await retention.run(now + timedelta(days=1))
        return await warnings_for(session, owner)

    warnings = async_database.run(scenario)
    # Assert
    assert warnings == []
