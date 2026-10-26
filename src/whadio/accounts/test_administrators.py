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


class MissingAdministrator:
    async def enabled(self, user_id: UUID) -> bool:
        del user_id
        return False

    async def set_enabled(self, user_id: UUID, *, enabled: bool) -> bool:
        del user_id, enabled
        return False


def test_operator_cannot_grant_permission_to_a_missing_account() -> None:
    # Arrange
    service = AdministratorService(MissingAdministrator())
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(service.set_enabled(uuid4(), enabled=True))
    # Assert
    assert failure.value.code == Failure.NOT_FOUND
