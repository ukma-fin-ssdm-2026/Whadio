from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..shared.errors import Failure, UseCaseError
from .models import User


class IAdministratorRepository(Protocol):
    async def enabled(self, user_id: UUID) -> bool: ...

    async def set_enabled(self, user_id: UUID, *, enabled: bool) -> bool: ...


class AdministratorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def enabled(self, user_id: UUID) -> bool:
        return bool(
            await self._session.scalar(select(User.is_administrator).where(User.user_id == user_id))
        )

    async def set_enabled(self, user_id: UUID, *, enabled: bool) -> bool:
        found = await self._session.scalar(
            update(User)
            .where(User.user_id == user_id)
            .values(is_administrator=enabled)
            .returning(User.user_id)
        )
        return found is not None


class AdministratorService:
    def __init__(self, repository: IAdministratorRepository) -> None:
        self._repository: IAdministratorRepository = repository

    async def require(self, user_id: UUID) -> None:
        if not await self._repository.enabled(user_id):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)

    async def set_enabled(self, user_id: UUID, *, enabled: bool) -> None:
        if not await self._repository.set_enabled(user_id, enabled=enabled):
            raise UseCaseError(Failure.NOT_FOUND)
