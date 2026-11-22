import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID, uuid4

import pytest
from psycopg.errors import LockNotAvailable
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.database import Database, DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .models import PasswordReset, User
from .password_resets import (
    IPasswordResetMailQueue,
    PasswordResetCleanupService,
    PasswordResetLink,
    PasswordResetMail,
    PasswordResetMailKind,
    PasswordResetRenewal,
    PasswordResetRequestService,
)
from .repositories import SessionRepository
from .reset_repository import PasswordResetRepository
from .test_password_resets import PASSWORD
from .test_password_resets import service as operator_service

pytestmark = pytest.mark.slow


class ResetMailQueue:
    def __init__(self) -> None:
        self.messages: list[PasswordResetMail] = []

    async def reserve(self, mail: PasswordResetMail, /) -> None:
        self.messages.append(mail)


@dataclass
class ResetClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


class DelayedMailQueue(ResetMailQueue):
    def __init__(self, clock: ResetClock) -> None:
        super().__init__()
        self._clock: ResetClock = clock

    @override
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        self._clock.now += timedelta(minutes=1)
        await super().reserve(mail)


class PausedMailQueue(ResetMailQueue):
    def __init__(self) -> None:
        super().__init__()
        self.reserving: asyncio.Event = asyncio.Event()
        self.resume: asyncio.Event = asyncio.Event()

    @override
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        self.reserving.set()
        await self.resume.wait()
        await super().reserve(mail)


class DelayedAccountLock(SessionRepository):
    def __init__(self, session: AsyncSession, clock: ResetClock) -> None:
        super().__init__(session)
        self._clock: ResetClock = clock

    @override
    async def account_for_update(self, email: str) -> User | None:
        user = await super().account_for_update(email)
        self._clock.now += timedelta(minutes=1)
        return user


def requests(
    session: AsyncSession, mail: IPasswordResetMailQueue, clock: ResetClock
) -> PasswordResetRequestService:
    return PasswordResetRequestService(
        PasswordResetRepository(session), SessionRepository(session), mail, clock
    )


async def sent_link(session: AsyncSession, mail: PasswordResetMail) -> PasswordResetLink:
    """The link the scheduler would mail, with the token it makes at sending."""
    renewed = await PasswordResetRenewal(
        PasswordResetRepository(session), SessionRepository(session)
    ).renew(mail.reset_id, mail.issued_at, mail.issued_at)
    if renewed is None:
        raise AssertionError("the queued link is no longer current")
    return renewed.link


@pytest.mark.parametrize("kind", list(PasswordResetMailKind))
def test_known_address_queues_a_one_hour_link(
    async_database: AsyncDatabase, kind: PasswordResetMailKind
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID, PasswordResetMail, datetime]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        now = datetime.now(UTC)
        # Act
        await requests(session, mail, ResetClock(now)).request(user.email.upper(), kind=kind)
        (queued,) = mail.messages
        pending = await session.get_one(PasswordReset, queued.reset_id)
        return user.user_id, queued, pending.expires_at

    user_id, queued, expires_at = async_database.run(scenario)
    # Assert
    assert (queued.user_id, queued.kind, queued.expires_at, expires_at) == (
        user_id,
        kind,
        queued.issued_at + timedelta(hours=1),
        queued.issued_at + timedelta(hours=1),
    )


def test_unknown_address_queues_nothing(async_database: AsyncDatabase) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> None:
        resets = requests(session, mail, ResetClock(datetime.now(UTC)))
        # Act
        await resets.request(f"{uuid4()}@example.com", kind=PasswordResetMailKind.RESET)

    async_database.run(scenario)
    # Assert
    assert mail.messages == []


def test_each_account_has_its_own_reset_link_and_cooldown(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        first = await AsyncDatabase.add_account(session, PASSWORD)
        second = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        resets = requests(session, mail, ResetClock(datetime.now(UTC)))
        # Act
        await resets.request(first.email, kind=PasswordResetMailKind.RESET)
        await resets.request(second.email, kind=PasswordResetMailKind.SIGN_IN_REMINDER)
        actual = [
            (notice.user_id, (await session.get_one(PasswordReset, notice.reset_id)).user_id)
            for notice in mail.messages
        ]
        return actual == [(first.user_id, first.user_id), (second.user_id, second.user_id)]

    # Assert
    assert async_database.run(scenario)


@pytest.mark.parametrize("first_kind", list(PasswordResetMailKind))
def test_either_form_shares_the_cooldown_and_preserves_the_first_link(
    async_database: AsyncDatabase, first_kind: PasswordResetMailKind
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        now = datetime.now(UTC)
        clock = ResetClock(now)
        resets = requests(session, mail, clock)
        second_kind = next(kind for kind in PasswordResetMailKind if kind != first_kind)
        await resets.request(user.email, kind=first_kind)
        # Act
        clock.now += timedelta(minutes=20, microseconds=-1)
        await resets.request(user.email.upper(), kind=second_kind)
        first = await sent_link(session, mail.messages[0])
        await operator_service(session).complete(first.reset_id, first.token, PASSWORD, clock.now)
        return len(mail.messages)

    # Assert
    assert async_database.run(scenario) == 1


def test_replacing_a_reset_link_starts_a_new_cooldown(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[Failure, list[timedelta]]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        clock = ResetClock(datetime.now(UTC))
        first_request = clock.now
        resets = requests(session, mail, clock)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        first = await sent_link(session, mail.messages[0])
        # Act
        clock.now += timedelta(minutes=19)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        clock.now += timedelta(minutes=1)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        clock.now += timedelta(minutes=1)
        await resets.request(user.email, kind=PasswordResetMailKind.SIGN_IN_REMINDER)
        _, replacement = mail.messages
        completion = operator_service(session)
        with pytest.raises(UseCaseError) as failure:
            await completion.complete(first.reset_id, first.token, PASSWORD, clock.now)
        link = await sent_link(session, replacement)
        await completion.complete(link.reset_id, link.token, PASSWORD, clock.now)
        return failure.value.code, [notice.issued_at - first_request for notice in mail.messages]

    # Assert
    assert async_database.run(scenario) == (
        Failure.LINK_INVALID,
        [timedelta(), timedelta(minutes=20)],
    )


def test_cooldown_survives_using_the_link(async_database: AsyncDatabase) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        clock = ResetClock(datetime.now(UTC))
        resets = requests(session, mail, clock)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        await session.flush()
        link = await sent_link(session, mail.messages[0])
        await operator_service(session).complete(link.reset_id, link.token, PASSWORD, clock.now)
        # Act
        clock.now += timedelta(minutes=1)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)

    async_database.run(scenario)
    # Assert
    assert len(mail.messages) == 1


def test_cooldown_starts_after_waiting_for_the_account_lock(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[timedelta]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        request_start = datetime.now(UTC)
        clock = ResetClock(request_start)
        mail = ResetMailQueue()
        blocked = PasswordResetRequestService(
            PasswordResetRepository(session), DelayedAccountLock(session, clock), mail, clock
        )
        await blocked.request(user.email, kind=PasswordResetMailKind.RESET)
        # Act
        clock.now = request_start + timedelta(minutes=20)
        await requests(session, mail, clock).request(user.email, kind=PasswordResetMailKind.RESET)
        return [notice.issued_at - request_start for notice in mail.messages]

    # Assert
    assert async_database.run(scenario) == [timedelta(minutes=1)]


def test_cooldown_starts_when_the_queue_reservation_finishes(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        request_start = datetime.now(UTC)
        clock = ResetClock(request_start)
        mail = DelayedMailQueue(clock)
        resets = requests(session, mail, clock)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        # Act
        clock.now = request_start + timedelta(minutes=20)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        return len(mail.messages)

    # Assert
    assert async_database.run(scenario) == 1


def test_operator_links_leave_the_email_cooldown_unchanged(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        clock = ResetClock(now)
        mail = ResetMailQueue()
        resets = requests(session, mail, clock)
        operator = operator_service(session)
        await operator.issue(user.email, now)
        # Act
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        clock.now += timedelta(minutes=1)
        manual_link = await operator.issue(user.email, clock.now)
        await resets.request(user.email, kind=PasswordResetMailKind.RESET)
        await operator.complete(manual_link.reset_id, manual_link.token, PASSWORD, clock.now)
        account = await session.get_one(User, user.user_id, populate_existing=True)
        return len(mail.messages), account.password_reset_mail_queued_at == now

    # Assert
    assert async_database.run(scenario) == (1, True)


def test_rollback_preserves_existing_link_and_email_cooldown(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        email = user.email
        now = datetime.now(UTC)
        existing = await operator_service(session).issue(email, now)
        mail = ResetMailQueue()
        resets = requests(session, mail, ResetClock(now))
        # Act
        async with session.begin_nested() as savepoint:
            await resets.request(email, kind=PasswordResetMailKind.RESET)
            await session.flush()
            await savepoint.rollback()
        pending = await session.get_one(PasswordReset, existing.reset_id, populate_existing=True)
        restored_hash = pending.token_hash
        await resets.request(email, kind=PasswordResetMailKind.RESET)
        return len(mail.messages), restored_hash == hashlib.sha256(
            existing.token.encode()
        ).hexdigest()

    # Assert
    assert async_database.run(scenario) == (2, True)


def test_parallel_requests_queue_only_one_email(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> tuple[int, bool]:
        database = Database(database_settings)
        mail = PausedMailQueue()
        user_id: UUID | None = None
        now = datetime.now(UTC)
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, PASSWORD)
                user_id, email = user.user_id, user.email

            async def request(kind: PasswordResetMailKind) -> None:
                async with database.transaction() as session:
                    await requests(session, mail, ResetClock(now)).request(email, kind=kind)

            async def overlap() -> bool:
                lock_held = False
                async with asyncio.TaskGroup() as group:
                    group.create_task(request(PasswordResetMailKind.RESET))
                    await mail.reserving.wait()
                    try:
                        async with database.transaction() as session:
                            await session.scalar(
                                select(User.user_id)
                                .where(User.user_id == user_id)
                                .with_for_update(nowait=True, read=True)
                            )
                    except OperationalError as error:
                        if not isinstance(error.orig, LockNotAvailable):
                            raise
                        lock_held = True
                    group.create_task(request(PasswordResetMailKind.SIGN_IN_REMINDER))
                    mail.resume.set()
                return lock_held

            # Act
            lock_held = await asyncio.wait_for(overlap(), timeout=15)
            return len(mail.messages), lock_held
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == (1, True)


def test_expired_reset_cleanup_cannot_erase_a_reissued_link(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario() -> int:
        database = Database(database_settings)
        selected, resume = asyncio.Event(), asyncio.Event()
        mail = ResetMailQueue()
        now = datetime.now(UTC)
        user_id: UUID | None = None
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, PASSWORD)
                user_id, email = user.user_id, user.email
                await operator_service(session).issue(email, now - timedelta(hours=2))

            async def request() -> None:
                async with database.transaction() as session:
                    flush = session.flush

                    async def paused_flush() -> None:
                        selected.set()
                        await resume.wait()
                        await flush()

                    with monkeypatch.context() as patch:
                        patch.setattr(session, "flush", paused_flush)
                        await requests(session, mail, ResetClock(now)).request(
                            email, kind=PasswordResetMailKind.RESET
                        )

            async def overlap() -> None:
                async with asyncio.TaskGroup() as group:
                    group.create_task(request())
                    await selected.wait()
                    try:
                        async with database.transaction() as session:
                            await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
                            await PasswordResetCleanupService(
                                PasswordResetRepository(session)
                            ).remove_expired(now)
                    except OperationalError as error:
                        if not isinstance(error.orig, LockNotAvailable):
                            raise
                    finally:
                        resume.set()

            # Act
            await asyncio.wait_for(overlap(), timeout=15)
            async with database.transaction() as session:
                await PasswordResetCleanupService(PasswordResetRepository(session)).remove_expired(
                    now
                )
                (queued,) = mail.messages
                link = await sent_link(session, queued)
                await operator_service(session).complete(link.reset_id, link.token, PASSWORD, now)
            return len(mail.messages)
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == 1
