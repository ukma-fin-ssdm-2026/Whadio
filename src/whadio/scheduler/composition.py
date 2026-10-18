from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.contracts import UserProfile
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..meetings.retention import IRetentionMeetings, IRetentionNotifier, RetentionMeetings
from ..notifications.repositories import NotificationOutboxRepository
from ..notifications.services import DeliveryUnit, NotificationDrainer, Recipient
from ..notifications.settings import NotificationSettings
from ..notifications.smtp import SmtpMailSender
from ..notifications.templates import AppLinks
from ..shared.database import Database, IUseCaseTransactions


class RetentionTransactions:
    def __init__(
        self, database: Database, notifications: Callable[[AsyncSession], IRetentionNotifier]
    ) -> None:
        self._database: Database = database
        self._notifications: Callable[[AsyncSession], IRetentionNotifier] = notifications

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
        async with self._database.transaction() as session:
            yield RetentionMeetings(
                session,
                AccessPolicy(
                    AccessRepository(session),
                    WorkspaceMembershipService(MembershipRepository(session)),
                ),
                self._notifications(session),
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
