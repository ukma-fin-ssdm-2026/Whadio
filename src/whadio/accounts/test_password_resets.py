import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.errors import Failure, UseCaseError
from .enums import SessionKind
from .models import PasswordReset, Session
from .password_resets import PasswordResetService, PasswordResetValidationError
from .passwords import Argon2PasswordHasher
from .reset_repository import PasswordResetRepository

pytestmark = pytest.mark.slow
PASSWORD = f"  A1{uuid4().hex}  "


def service(session: AsyncSession) -> PasswordResetService:
    return PasswordResetService(PasswordResetRepository(session), Argon2PasswordHasher())


def test_issuance_stores_only_a_hash_with_one_hour_lifetime(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        # Act
        link = await service(session).issue(user.email.upper(), now)
        pending = await session.get(PasswordReset, link.reset_id)
        return (
            pending is not None
            and pending.token_hash == hashlib.sha256(link.token.encode()).hexdigest()
            and pending.expires_at == now + timedelta(hours=1)
            and link.token not in repr(link)
        )

    # Assert
    assert async_database.run(scenario)


def test_issuance_refuses_an_unknown_account(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        # Act
        with pytest.raises(UseCaseError) as error:
            await service(session).issue(f"{uuid4()}@example.com", datetime.now(UTC))
        return error.value.code

    # Assert
    assert async_database.run(scenario) is Failure.NOT_FOUND


@pytest.mark.parametrize("offset", [timedelta(hours=1), timedelta(hours=2)])
def test_expiry_includes_the_exact_boundary(
    async_database: AsyncDatabase, offset: timedelta
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        link = await service(session).issue(user.email, now)
        # Act
        with pytest.raises(UseCaseError) as error:
            await service(session).complete(link.reset_id, link.token, PASSWORD, now + offset)
        return error.value.code

    # Assert
    assert async_database.run(scenario) is Failure.LINK_INVALID


def test_reset_works_just_before_expiry_and_preserves_password_spaces(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, f"Old1{uuid4().hex}")
        now = datetime.now(UTC)
        link = await service(session).issue(user.email, now)
        # Act
        await service(session).complete(
            link.reset_id, link.token, PASSWORD, now + timedelta(hours=1, microseconds=-1)
        )
        await session.refresh(user)
        return Argon2PasswordHasher().verify(user.password_hash, PASSWORD)

    # Assert
    assert async_database.run(scenario)


@pytest.mark.parametrize("password", ["shortA1", "lowercase123456", "UppercaseOnly", "A1" * 65])
def test_invalid_password_leaves_link_and_password_unchanged(
    async_database: AsyncDatabase, password: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        original = user.password_hash
        now = datetime.now(UTC)
        link = await service(session).issue(user.email, now)
        # Act
        with pytest.raises(PasswordResetValidationError):
            await service(session).complete(link.reset_id, link.token, password, now)
        await session.refresh(user)
        return (
            user.password_hash == original
            and await session.get(PasswordReset, link.reset_id) is not None
        )

    # Assert
    assert async_database.run(scenario)


def test_transaction_failure_rolls_back_password_sessions_and_link(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        user_id, original = user.user_id, user.password_hash
        now = datetime.now(UTC)
        link = await service(session).issue(user.email, now)
        token_hash = hashlib.sha256(uuid4().bytes).hexdigest()
        session.add(
            Session(
                user_id=user_id,
                kind=SessionKind.BROWSER,
                token_hash=token_hash,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.flush()

        async def abort() -> None:
            async with session.begin_nested():
                await service(session).complete(link.reset_id, link.token, PASSWORD, now)
                raise RuntimeError("abort")

        # Act
        with pytest.raises(RuntimeError, match="abort"):
            await abort()
        await session.refresh(user)
        return (
            user.password_hash == original
            and await session.get(PasswordReset, link.reset_id) is not None
            and await session.scalar(
                select(Session.session_id).where(Session.token_hash == token_hash)
            )
            is not None
        )

    # Assert
    assert async_database.run(scenario)
