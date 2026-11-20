import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.database import Database, DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .models import PasswordReset, User
from .password_resets import (
    IPasswordResetMailQueue,
    PasswordResetMail,
    PasswordResetMailKind,
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


def requests(session: AsyncSession, mail: IPasswordResetMailQueue) -> PasswordResetRequestService:
    return PasswordResetRequestService(
        PasswordResetRepository(session), SessionRepository(session), mail
    )


@pytest.mark.parametrize("kind", list(PasswordResetMailKind))
def test_known_address_queues_a_one_hour_link(
    async_database: AsyncDatabase, kind: PasswordResetMailKind
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID, PasswordResetMail, datetime, str]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        now = datetime.now(UTC)
        # Act
        await requests(session, mail).request(user.email.upper(), now, kind=kind)
        (queued,) = mail.messages
        pending = await session.get_one(PasswordReset, queued.link.reset_id)
        return user.user_id, queued, pending.expires_at, pending.token_hash

    user_id, queued, expires_at, token_hash = async_database.run(scenario)
    # Assert
    assert (queued.user_id, queued.kind, queued.expires_at, expires_at, token_hash) == (
        user_id,
        kind,
        queued.queued_at + timedelta(hours=1),
        queued.queued_at + timedelta(hours=1),
        hashlib.sha256(queued.link.token.encode()).hexdigest(),
    )


def test_unknown_address_queues_nothing(async_database: AsyncDatabase) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> None:
        # Act
        await requests(session, mail).request(
            f"{uuid4()}@example.com", datetime.now(UTC), kind=PasswordResetMailKind.RESET
        )

    async_database.run(scenario)
    # Assert
    assert mail.messages == []


@pytest.mark.parametrize("first_kind", list(PasswordResetMailKind))
def test_either_form_shares_the_cooldown_and_preserves_the_first_link(
    async_database: AsyncDatabase, first_kind: PasswordResetMailKind
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        resets = requests(session, mail)
        now = datetime.now(UTC)
        second_kind = next(kind for kind in PasswordResetMailKind if kind != first_kind)
        await resets.request(user.email, now, kind=first_kind)
        first = mail.messages[0].link
        # Act
        repeat_at = now + timedelta(minutes=20, microseconds=-1)
        await resets.request(user.email.upper(), repeat_at, kind=second_kind)
        await operator_service(session).complete(first.reset_id, first.token, PASSWORD, repeat_at)
        return len(mail.messages)

    # Assert
    assert async_database.run(scenario) == 1


def test_request_at_twenty_minutes_replaces_the_link(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        mail = ResetMailQueue()
        resets = requests(session, mail)
        now = datetime.now(UTC)
        await resets.request(user.email, now, kind=PasswordResetMailKind.RESET)
        first = mail.messages[0].link
        # Act
        repeat_at = now + timedelta(minutes=20)
        await resets.request(user.email, repeat_at, kind=PasswordResetMailKind.RESET)
        _, replacement = mail.messages
        completion = operator_service(session)
        with pytest.raises(UseCaseError) as failure:
            await completion.complete(first.reset_id, first.token, PASSWORD, repeat_at)
        link = replacement.link
        await completion.complete(link.reset_id, link.token, PASSWORD, repeat_at)
        return failure.value.code

    # Assert
    assert async_database.run(scenario) is Failure.LINK_INVALID


def test_cooldown_survives_using_the_link(async_database: AsyncDatabase) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        resets = requests(session, mail)
        now = datetime.now(UTC)
        await resets.request(user.email, now, kind=PasswordResetMailKind.RESET)
        await session.flush()
        await operator_service(session).complete(
            mail.messages[0].link.reset_id, mail.messages[0].link.token, PASSWORD, now
        )
        # Act
        await resets.request(
            user.email, now + timedelta(minutes=1), kind=PasswordResetMailKind.RESET
        )

    async_database.run(scenario)
    # Assert
    assert len(mail.messages) == 1


def test_operator_link_does_not_start_the_email_cooldown(async_database: AsyncDatabase) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        await operator_service(session).issue(user.email, now)
        # Act
        await requests(session, mail).request(user.email, now, kind=PasswordResetMailKind.RESET)

    async_database.run(scenario)
    # Assert
    assert len(mail.messages) == 1


def test_rollback_preserves_existing_link_and_email_cooldown(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        email = user.email
        now = datetime.now(UTC)
        existing = await operator_service(session).issue(email, now)
        mail = ResetMailQueue()
        # Act
        async with session.begin_nested() as savepoint:
            await requests(session, mail).request(email, now, kind=PasswordResetMailKind.RESET)
            await session.flush()
            await savepoint.rollback()
        pending = await session.get_one(PasswordReset, existing.reset_id, populate_existing=True)
        restored_hash = pending.token_hash
        await requests(session, mail).request(email, now, kind=PasswordResetMailKind.RESET)
        return len(mail.messages), restored_hash == hashlib.sha256(
            existing.token.encode()
        ).hexdigest()

    # Assert
    assert async_database.run(scenario) == (2, True)


def test_parallel_requests_queue_only_one_email(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> int:
        database = Database(database_settings)
        mail = ResetMailQueue()
        user_id: UUID | None = None
        now = datetime.now(UTC)
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, PASSWORD)
                user_id, email = user.user_id, user.email

            async def request(kind: PasswordResetMailKind) -> None:
                async with database.transaction() as session:
                    await requests(session, mail).request(email, now, kind=kind)

            # Act
            await asyncio.wait_for(
                asyncio.gather(*(request(kind) for kind in PasswordResetMailKind)), timeout=15
            )
            return len(mail.messages)
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == 1
