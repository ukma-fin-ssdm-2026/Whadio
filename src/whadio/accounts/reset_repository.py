from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PasswordReset, Session, User


class IPasswordResetRepository(Protocol):
    async def account(self, email: str, /) -> User | None: ...

    async def lock_account(self, user_id: UUID, /) -> None: ...

    async def pending(self, reset_id: UUID, /) -> PasswordReset | None: ...

    async def issue(
        self, user_id: UUID, token_hash: str, now: datetime, expires_at: datetime, /
    ) -> UUID: ...

    async def complete(self, user_id: UUID, reset_id: UUID, password_hash: str, /) -> None: ...


class PasswordResetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def account(self, email: str) -> User | None:
        return await self._session.scalar(
            select(User)
            .where(func.lower(User.email) == email.lower())
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )

    async def lock_account(self, user_id: UUID) -> None:
        await self._session.scalar(
            select(User.user_id).where(User.user_id == user_id).with_for_update(key_share=True)
        )

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
