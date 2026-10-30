from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.contracts import UserProfile
from ..accounts.password_resets import PasswordResetCleanupService
from ..accounts.repositories import MembershipRepository, RegistrationRepository
from ..accounts.reset_repository import PasswordResetRepository
from ..accounts.services import RegistrationCleanupService, WorkspaceMembershipService
from ..meetings.models import Meeting
from ..meetings.repositories import MeetingRepository
from ..meetings.retention import IRetentionMeetings, RetentionMeetings
from ..notifications.repositories import INotificationOutbox, NotificationOutboxRepository
from ..notifications.services import DeliveryUnit, NotificationDrainer, Recipient
from ..notifications.settings import NotificationSettings
from ..notifications.smtp import SmtpMailSender
from ..notifications.templates import AppLinks, NoticeKind, RecordingDeletionWarning
from ..shared.database import IUseCaseTransactions


class IMeetingRecords(Protocol):
    async def get(self, meeting_id: UUID, /) -> Meeting: ...


class OutboxRetentionNotices:
    """Meetings' `IRetentionNotifier`, answered by the notification outbox."""

    def __init__(self, outbox: INotificationOutbox, meetings: IMeetingRecords) -> None:
        self._outbox: INotificationOutbox = outbox
        self._meetings: IMeetingRecords = meetings

    async def enqueue(self, meeting_id: UUID, recipient_id: UUID, deadline: datetime) -> None:
        meeting = await self._meetings.get(meeting_id)
        await self._outbox.reserve(
            recipient_id,
            f"{NoticeKind.RECORDING_DELETION_WARNING}:{meeting_id}:{recipient_id}",
            RecordingDeletionWarning(
                meeting_id=meeting_id, meeting_name=meeting.name, deletes_at=deadline
            ),
        )


class RetentionTransactions:
    def __init__(self, database: IUseCaseTransactions) -> None:
        self._database: IUseCaseTransactions = database

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
        async with self._database.transaction() as session:
            yield RetentionMeetings(
                session,
                AccessPolicy(
                    AccessRepository(session),
                    WorkspaceMembershipService(MembershipRepository(session)),
                ),
                OutboxRetentionNotices(
                    NotificationOutboxRepository(session), MeetingRepository(session)
                ),
            )


class IProfiles(Protocol):
    async def profile(self, user_id: UUID, /) -> UserProfile | None: ...


class AccountRecipients:
    """Notifications' `IRecipientDirectory`, answered by Accounts."""

    def __init__(self, profiles: IProfiles) -> None:
        self._profiles: IProfiles = profiles

    async def recipient(self, user_id: UUID) -> Recipient | None:
        profile = await self._profiles.profile(user_id)
        return None if profile is None else Recipient(profile.name, profile.email)


class DeliveryTransactions:
    def __init__(self, database: IUseCaseTransactions) -> None:
        self._database: IUseCaseTransactions = database

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[DeliveryUnit]:
        async with self._database.transaction() as session:
            yield DeliveryUnit(
                NotificationOutboxRepository(session),
                AccountRecipients(WorkspaceMembershipService(MembershipRepository(session))),
            )


class RegistrationCleanupJobs:
    def __init__(self, database: IUseCaseTransactions) -> None:
        self._database: IUseCaseTransactions = database

    async def remove_expired(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            return await RegistrationCleanupService(RegistrationRepository(session)).remove_expired(
                now
            )

    async def remove_expired_password_resets(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            return await PasswordResetCleanupService(
                PasswordResetRepository(session)
            ).remove_expired(now)


def notification_drainer(
    settings: NotificationSettings, database: IUseCaseTransactions
) -> NotificationDrainer | None:
    """None without a relay: notices are still reserved, and wait for one (FR-047)."""
    delivery = settings.delivery()
    if delivery is None:
        return None
    return NotificationDrainer(
        DeliveryTransactions(database),
        SmtpMailSender(delivery.smtp),
        AppLinks(delivery.public_url),
        settings.outbox,
    )
