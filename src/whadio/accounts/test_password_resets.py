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
from .password_resets import (
    PasswordResetRenewal,
    PasswordResetService,
    PasswordResetValidationError,
    RenewedPasswordReset,
)
from .passwords import Argon2PasswordHasher
from .repositories import SessionRepository
from .reset_repository import PasswordResetRepository

pytestmark = pytest.mark.slow
PASSWORD = f"  A1{uuid4().hex}  "


def service(session: AsyncSession) -> PasswordResetService:
    return PasswordResetService(
        PasswordResetRepository(session), SessionRepository(session), Argon2PasswordHasher()
    )


def renewal(session: AsyncSession) -> PasswordResetRenewal:
    return PasswordResetRenewal(PasswordResetRepository(session), SessionRepository(session))


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


def test_reissuing_a_link_refreshes_its_lifetime(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        first_now = datetime.now(UTC)
        first = await service(session).issue(user.email, first_now)
        second_now = first_now + timedelta(minutes=30)
        # Act
        second = await service(session).issue(user.email.upper(), second_now)
        pending = await session.get(PasswordReset, second.reset_id)
        try:
            await service(session).complete(first.reset_id, first.token, PASSWORD, second_now)
        except UseCaseError as error:
            first_is_invalid = error.code is Failure.LINK_INVALID
        else:
            first_is_invalid = False
        await service(session).complete(
            second.reset_id, second.token, PASSWORD, second_now + timedelta(minutes=59)
        )
        return (
            pending is not None
            and pending.created_at == second_now
            and pending.expires_at == second_now + timedelta(hours=1),
            first_is_invalid,
            await session.get(PasswordReset, second.reset_id) is None,
        )

    # Assert
    assert async_database.run(scenario) == (True, True, True)


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


def test_renewed_reset_link_is_for_its_account_and_completes_it(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        issued = await service(session).issue(user.email, now)
        # Act
        renewed = await renewal(session).renew(issued.reset_id, now, now)
        if renewed is None:
            raise AssertionError("the current link was not renewed")
        await service(session).complete(issued.reset_id, renewed.link.token, PASSWORD, now)
        return (
            renewed.user_id == user.user_id
            and await session.get(PasswordReset, issued.reset_id) is None
        )

    # Assert
    assert async_database.run(scenario)


def test_renewal_stops_the_earlier_reset_link(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        issued = await service(session).issue(user.email, now)
        # Act
        await renewal(session).renew(issued.reset_id, now, now)
        with pytest.raises(UseCaseError) as error:
            await service(session).complete(issued.reset_id, issued.token, PASSWORD, now)
        return error.value.code

    # Assert
    assert async_database.run(scenario) is Failure.LINK_INVALID


@pytest.mark.parametrize("stale", ["issued again", "expired", "used"])
def test_reset_renewal_refuses_a_stale_link(async_database: AsyncDatabase, stale: str) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> RenewedPasswordReset | None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        issued = await service(session).issue(user.email, now)
        renewed_at = now + timedelta(hours=1) if stale == "expired" else now
        if stale == "issued again":
            await service(session).issue(user.email, now + timedelta(minutes=30))
        if stale == "used":
            await service(session).complete(issued.reset_id, issued.token, PASSWORD, now)
        # Act
        return await renewal(session).renew(issued.reset_id, now, renewed_at)

    # Assert
    assert async_database.run(scenario) is None
