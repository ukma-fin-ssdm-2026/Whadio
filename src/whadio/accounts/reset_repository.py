from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PasswordReset, Session, User


class IPasswordResetRepository(Protocol):
    async def pending(self, reset_id: UUID, /) -> PasswordReset | None: ...

    async def issue(
        self, user_id: UUID, token_hash: str, now: datetime, expires_at: datetime, /
    ) -> UUID: ...

    async def complete(self, user_id: UUID, reset_id: UUID, password_hash: str, /) -> None: ...

    async def delete_expired(self, now: datetime, /) -> int: ...


class PasswordResetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def pending(self, reset_id: UUID) -> PasswordReset | None:
        return await self._session.scalar(
            select(PasswordReset)
            .where(PasswordReset.password_reset_id == reset_id)
            .execution_options(populate_existing=True)
        )

    async def issue(
        self, user_id: UUID, token_hash: str, now: datetime, expires_at: datetime
    ) -> UUID:
        pending = await self._session.scalar(
            select(PasswordReset).where(PasswordReset.user_id == user_id)
        )
        if pending is None:
            pending = PasswordReset(user_id=user_id)
            self._session.add(pending)
        pending.token_hash = token_hash
        pending.created_at = now
        pending.expires_at = expires_at
        await self._session.flush()
        return pending.password_reset_id

    async def complete(self, user_id: UUID, reset_id: UUID, password_hash: str) -> None:
        await self._session.execute(
            update(User).where(User.user_id == user_id).values(password_hash=password_hash)
        )
        await self._session.execute(delete(Session).where(Session.user_id == user_id))
        await self._session.execute(
            delete(PasswordReset).where(PasswordReset.password_reset_id == reset_id)
        )

    async def delete_expired(self, now: datetime) -> int:
        deleted = await self._session.scalars(
            delete(PasswordReset)
            .where(PasswordReset.expires_at <= now)
            .returning(PasswordReset.password_reset_id)
        )
        return len(deleted.all())
