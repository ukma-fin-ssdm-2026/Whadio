import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.errors import Failure, UseCaseError
from .administrators import AdministratorRepository, AdministratorService


@pytest.mark.slow
@pytest.mark.parametrize("enabled", [True, False])
def test_operator_permission_changes_are_idempotent(
    async_database: AsyncDatabase, *, enabled: bool
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        actor, _ = await AsyncDatabase.add_workspace(session)
        repository = AdministratorRepository(session)
        service = AdministratorService(repository)
        # Act
        await service.set_enabled(actor, enabled=enabled)
        await service.set_enabled(actor, enabled=enabled)
        return await repository.enabled(actor)

    found = async_database.run(scenario)
    # Assert
    assert found is enabled


@pytest.mark.slow
def test_operator_grant_by_email_changes_only_that_account(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        email = f"Alice-{uuid4()}@Example.test"
        account = await AsyncDatabase.add_account(session, uuid4().hex, email)
        other = await AsyncDatabase.add_account(session, uuid4().hex)
        repository = AdministratorRepository(session)
        # Act
        await AdministratorService(repository).set_enabled_by_email(email.upper(), enabled=True)
        return await repository.enabled(account.user_id), await repository.enabled(other.user_id)

    found = async_database.run(scenario)
    # Assert
    assert found == (True, False)


class MissingAdministrator:
    async def enabled(self, user_id: UUID) -> bool:
        del user_id
        return False

    async def set_enabled(self, user_id: UUID, *, enabled: bool) -> bool:
        del user_id, enabled
        return False

    async def set_enabled_by_email(self, email: str, *, enabled: bool) -> bool:
        del email, enabled
        return False


def test_operator_cannot_grant_permission_to_a_missing_account() -> None:
    # Arrange
    service = AdministratorService(MissingAdministrator())
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(service.set_enabled(uuid4(), enabled=True))
    # Assert
    assert failure.value.code == Failure.NOT_FOUND


def test_operator_cannot_grant_permission_to_a_missing_email() -> None:
    # Arrange
    service = AdministratorService(MissingAdministrator())
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(service.set_enabled_by_email("nobody@example.com", enabled=True))
    # Assert
    assert failure.value.code == Failure.NOT_FOUND
