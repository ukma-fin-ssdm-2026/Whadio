import asyncio
from datetime import UTC, datetime
from typing import override
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.database import Database, DatabaseSettings
from ..shared.errors import UseCaseError
from .enums import SessionKind
from .models import User
from .password_resets import PasswordResetLink, PasswordResetService
from .passwords import Argon2PasswordHasher
from .repositories import SessionRepository
from .reset_repository import PasswordResetRepository
from .services import SignInService

pytestmark = pytest.mark.slow


def test_concurrent_redemption_has_one_winner(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> list[str]:
        database = Database(database_settings)
        user_id: UUID | None = None
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, "OriginalPassword1")
                user_id = user.user_id
                link = await PasswordResetService(
                    PasswordResetRepository(session),
                    SessionRepository(session),
                    Argon2PasswordHasher(),
                ).issue(user.email, datetime.now(UTC))

            async def redeem() -> str:
                try:
                    async with database.transaction() as session:
                        await PasswordResetService(
                            PasswordResetRepository(session),
                            SessionRepository(session),
                            Argon2PasswordHasher(),
                        ).complete(
                            link.reset_id, link.token, "ReplacementPassword1", datetime.now(UTC)
                        )
                except UseCaseError as error:
                    return error.code.value
                return "reset"

            # Act
            return sorted(await asyncio.wait_for(asyncio.gather(redeem(), redeem()), timeout=15))
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == [
        "LINK_INVALID",
        "reset",
    ]


class PausedSessionRepository(SessionRepository):
    def __init__(
        self, session: AsyncSession, locked: asyncio.Event, release: asyncio.Event
    ) -> None:
        super().__init__(session)
        self._locked: asyncio.Event = locked
        self._release: asyncio.Event = release

    @override
    async def lock_account(self, user_id: UUID) -> None:
        await super().lock_account(user_id)
        self._locked.set()
        await self._release.wait()


class ObservedSessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession, started: asyncio.Event) -> None:
        super().__init__(session)
        self._started: asyncio.Event = started

    @override
    async def by_email(self, email: str) -> User | None:
        self._started.set()
        return await super().by_email(email)


class ObservedIssueSessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession, started: asyncio.Event) -> None:
        super().__init__(session)
        self._started: asyncio.Event = started

    @override
    async def account_for_update(self, email: str) -> User | None:
        self._started.set()
        return await super().account_for_update(email)


def test_sign_in_waiting_for_reset_cannot_use_old_password(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> str:
        database = Database(database_settings)
        locked, release, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        user_id: UUID | None = None
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, "OriginalPassword1")
                user_id, email = user.user_id, user.email
                link = await PasswordResetService(
                    PasswordResetRepository(session),
                    SessionRepository(session),
                    Argon2PasswordHasher(),
                ).issue(email, datetime.now(UTC))

            async def reset() -> None:
                async with database.transaction() as session:
                    await PasswordResetService(
                        PasswordResetRepository(session),
                        PausedSessionRepository(session, locked, release),
                        Argon2PasswordHasher(),
                    ).complete(link.reset_id, link.token, "ReplacementPassword1", datetime.now(UTC))

            async def sign_in() -> str:
                await locked.wait()
                try:
                    async with database.transaction() as session:
                        await SignInService(
                            ObservedSessionRepository(session, started), Argon2PasswordHasher()
                        ).sign_in(
                            email, "OriginalPassword1", SessionKind.BROWSER, datetime.now(UTC)
                        )
                except UseCaseError as error:
                    return error.code.value
                return "signed in"

            async def finish() -> str:
                async with asyncio.TaskGroup() as group:
                    group.create_task(reset())
                    signed = group.create_task(sign_in())
                    await started.wait()
                    release.set()
                return signed.result()

            # Act
            return await asyncio.wait_for(finish(), timeout=15)
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == "INVALID_CREDENTIALS"


def test_issuance_waiting_for_reset_replaces_the_used_link(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[str, str]:
        database = Database(database_settings)
        user_id: UUID | None = None
        locked, release, issuing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        try:
            async with database.transaction() as session:
                user = await AsyncDatabase.add_account(session, "OriginalPassword1")
                user_id = user.user_id
                old_link = await PasswordResetService(
                    PasswordResetRepository(session),
                    SessionRepository(session),
                    Argon2PasswordHasher(),
                ).issue(user.email, datetime.now(UTC))

            async def reset() -> None:
                async with database.transaction() as session:
                    await PasswordResetService(
                        PasswordResetRepository(session),
                        PausedSessionRepository(session, locked, release),
                        Argon2PasswordHasher(),
                    ).complete(
                        old_link.reset_id,
                        old_link.token,
                        "ReplacementPassword1",
                        datetime.now(UTC),
                    )

            async def reissue() -> PasswordResetLink:
                await locked.wait()
                async with database.transaction() as session:
                    return await PasswordResetService(
                        PasswordResetRepository(session),
                        ObservedIssueSessionRepository(session, issuing),
                        Argon2PasswordHasher(),
                    ).issue(user.email, datetime.now(UTC))

            async with asyncio.TaskGroup() as group:
                group.create_task(reset())
                new_link = group.create_task(reissue())
                await issuing.wait()
                release.set()
            async with database.transaction() as session:
                service = PasswordResetService(
                    PasswordResetRepository(session),
                    SessionRepository(session),
                    Argon2PasswordHasher(),
                )
                old_result = "reset redeemed"
                try:
                    await service.complete(
                        old_link.reset_id,
                        old_link.token,
                        "AnotherPassword1",
                        datetime.now(UTC),
                    )
                except UseCaseError as error:
                    old_result = error.code.value
                await service.complete(
                    new_link.result().reset_id,
                    new_link.result().token,
                    "AnotherPassword1",
                    datetime.now(UTC),
                )
                return old_result, "new link redeemed"
        finally:
            async with database.transaction() as session:
                await session.execute(delete(User).where(User.user_id == user_id))
            await database.close()

    # Act
    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == ("LINK_INVALID", "new link redeemed")
