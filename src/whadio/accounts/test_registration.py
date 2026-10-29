from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.errors import Failure, UseCaseError
from .models import PendingRegistration, User
from .passwords import Argon2PasswordHasher
from .repositories import RegistrationRepository, SessionRepository
from .services import (
    RegistrationDetails,
    RegistrationIssuer,
    RegistrationLink,
    RegistrationService,
    RegistrationValidationError,
)

pytestmark = pytest.mark.slow
DETAILS = RegistrationDetails("Alice", f"A1{uuid4().hex}", accept_terms=True)


class Content:
    async def add_default_folder(self, workspace_id: UUID, now: datetime) -> None:
        del workspace_id, now

    async def remove_meetings(self, workspace_id: UUID, now: datetime) -> None:
        del workspace_id, now


class FailingContent(Content):
    @override
    async def add_default_folder(self, workspace_id: UUID, now: datetime) -> None:
        del workspace_id, now
        raise RuntimeError("Folder creation failed")


def service(session: AsyncSession, content: Content | None = None) -> RegistrationService:
    return RegistrationService(
        RegistrationRepository(session),
        SessionRepository(session),
        Argon2PasswordHasher(),
        content or Content(),
    )


async def issue(session: AsyncSession, email: str, now: datetime) -> RegistrationLink:
    return await RegistrationIssuer(
        RegistrationRepository(session), SessionRepository(session)
    ).issue(email, now)


@pytest.mark.parametrize("offset", [timedelta(hours=24), timedelta(hours=25)])
def test_expiry_includes_the_exact_boundary(
    async_database: AsyncDatabase, offset: timedelta
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        now = datetime.now(UTC)
        link = await issue(session, f"{uuid4()}@example.com", now)
        # Act
        with pytest.raises(UseCaseError) as failure:
            await service(session).complete(link.registration_id, link.token, DETAILS, now + offset)
        return failure.value.code

    # Assert
    assert async_database.run(scenario) is Failure.LINK_INVALID


def test_link_works_just_before_expiry(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        now = datetime.now(UTC)
        link = await issue(session, f"{uuid4()}@example.com", now)
        # Act
        signed = await service(session).complete(
            link.registration_id, link.token, DETAILS, now + timedelta(hours=24, microseconds=-1)
        )
        return signed.user.name

    # Assert
    assert async_database.run(scenario) == DETAILS.name


@pytest.mark.parametrize(
    "details",
    [
        RegistrationDetails("Alice", "weak", accept_terms=True),
        RegistrationDetails("Alice", DETAILS.password, accept_terms=False),
        RegistrationDetails("\u3164", DETAILS.password, accept_terms=True),
    ],
)
def test_service_refuses_invalid_account_details(
    async_database: AsyncDatabase,
    details: RegistrationDetails,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        link = await issue(session, f"{uuid4()}@example.com", datetime.now(UTC))
        # Act
        with pytest.raises(RegistrationValidationError):
            await service(session).complete(
                link.registration_id, link.token, details, datetime.now(UTC)
            )
        return await session.get(PendingRegistration, link.registration_id) is not None

    # Assert
    assert async_database.run(scenario)


def test_failed_folder_creation_rolls_back_registration(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        email = f"{uuid4()}@example.com"
        link = await issue(session, email, datetime.now(UTC))
        # Act
        with pytest.raises(RuntimeError, match="Folder creation failed"):
            async with session.begin_nested():
                await service(session, FailingContent()).complete(
                    link.registration_id, link.token, DETAILS, datetime.now(UTC)
                )
        return (
            await session.get(PendingRegistration, link.registration_id) is not None,
            await session.scalar(select(User.user_id).where(User.email == email)) is None,
        )

    # Assert
    assert async_database.run(scenario) == (True, True)
