from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.contracts import UserProfile
from ..accounts.password_resets import (
    PasswordResetCleanupService,
    PasswordResetRenewal,
    RenewedPasswordReset,
)
from ..accounts.repositories import (
    InvitationRepository,
    MembershipRepository,
    RegistrationRepository,
    SessionRepository,
)
from ..accounts.reset_repository import PasswordResetRepository
from ..accounts.services import (
    InvitationCleanupService,
    RegistrationCleanupService,
    RegistrationIssuer,
    RenewedRegistration,
    SessionCleanupService,
    WorkspaceMembershipService,
)
from ..meetings.models import Meeting
from ..meetings.repositories import MeetingRepository
from ..meetings.retention import IRetentionMeetings, RetentionMeetings
from ..notifications.repositories import INotificationOutbox, NotificationOutboxRepository
from ..notifications.services import (
    AccountLinkMail,
    DeliveryUnit,
    IRecipientDirectory,
    NotificationDrainer,
    Recipient,
)
from ..notifications.settings import NotificationSettings
from ..notifications.smtp import SmtpMailSender
from ..notifications.templates import (
    AccountLinkNotice,
    AppLinks,
    NoticeKind,
    PasswordResetNotice,
    RecordingDeletionWarning,
    RegistrationLinkNotice,
    SignInReminderNotice,
)
from ..processing.recovery import JobRecovery
from ..processing.repositories import JobRepository
from ..processing.settings import JobRecoverySettings
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


class IRegistrationRenewal(Protocol):
    async def renew(
        self, registration_id: UUID, issued_at: datetime, now: datetime, /
    ) -> RenewedRegistration | None: ...


class IPasswordResetRenewal(Protocol):
    async def renew(
        self, reset_id: UUID, issued_at: datetime, now: datetime, /
    ) -> RenewedPasswordReset | None: ...


class AccountLinkRenewal:
    """Notifications' `IAccountLinks`, answered by Accounts."""

    def __init__(
        self,
        registrations: IRegistrationRenewal,
        resets: IPasswordResetRenewal,
        recipients: IRecipientDirectory,
        public_url: str,
        now: Callable[[], datetime],
    ) -> None:
        self._registrations: IRegistrationRenewal = registrations
        self._resets: IPasswordResetRenewal = resets
        self._recipients: IRecipientDirectory = recipients
        self._public_url: str = public_url
        self._now: Callable[[], datetime] = now

    async def renew(self, notice: AccountLinkNotice) -> AccountLinkMail | None:
        match notice:
            case RegistrationLinkNotice():
                registration = await self._registrations.renew(
                    notice.registration_id, notice.issued_at, self._now()
                )
                if registration is None:
                    return None
                return AccountLinkMail(
                    Recipient("", registration.email), registration.link.url(self._public_url)
                )
            case PasswordResetNotice() | SignInReminderNotice():
                reset = await self._resets.renew(notice.reset_id, notice.issued_at, self._now())
                if reset is None:
                    return None
                recipient = await self._recipients.recipient(reset.user_id)
                if recipient is None:
                    return None
                return AccountLinkMail(recipient, reset.link.url(self._public_url))


class DeliveryTransactions:
    def __init__(self, database: IUseCaseTransactions, public_url: str) -> None:
        self._database: IUseCaseTransactions = database
        self._public_url: str = public_url

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[DeliveryUnit]:
        async with self._database.transaction() as session:
            recipients = AccountRecipients(
                WorkspaceMembershipService(MembershipRepository(session))
            )
            sessions = SessionRepository(session)
            yield DeliveryUnit(
                NotificationOutboxRepository(session),
                recipients,
                AccountLinkRenewal(
                    RegistrationIssuer(RegistrationRepository(session), sessions),
                    PasswordResetRenewal(PasswordResetRepository(session), sessions),
                    recipients,
                    self._public_url,
                    lambda: datetime.now(UTC),
                ),
            )


class RegistrationCleanupJobs:
    def __init__(self, database: IUseCaseTransactions) -> None:
        self._database: IUseCaseTransactions = database

    async def remove_expired(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            registrations = await RegistrationCleanupService(
                RegistrationRepository(session)
            ).remove_expired(now)
            invitations = await InvitationCleanupService(
                InvitationRepository(session)
            ).remove_expired(now)
            return registrations + invitations

    async def remove_expired_password_resets(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            return await PasswordResetCleanupService(
                PasswordResetRepository(session)
            ).remove_expired(now)

    async def remove_expired_sessions(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            return await SessionCleanupService(SessionRepository(session)).remove_expired(now)


def notification_drainer(
    settings: NotificationSettings, database: IUseCaseTransactions
) -> NotificationDrainer | None:
    """None without a relay: notices are still reserved, and wait for one (FR-047)."""
    delivery = settings.delivery()
    if delivery is None:
        return None
    return NotificationDrainer(
        DeliveryTransactions(database, str(delivery.public_url)),
        SmtpMailSender(delivery.smtp),
        AppLinks(delivery.public_url),
        settings.outbox,
    )


class JobRecoveryJobs:
    def __init__(self, database: IUseCaseTransactions, limits: JobRecoverySettings) -> None:
        self._database: IUseCaseTransactions = database
        self._limits: JobRecoverySettings = limits

    async def recover(self, now: datetime) -> int:
        async with self._database.transaction() as session:
            return await JobRecovery(JobRepository(session), self._limits).recover(now)
