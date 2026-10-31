import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from ..shared.errors import Failure, UseCaseError
from .passwords import IPasswordHasher, is_password_strong, password_rule_message
from .repositories import ISessionRepository
from .reset_repository import IPasswordResetRepository
from .tokens import supplied_token_hash

RESET_LIFETIME: Final = timedelta(hours=1)


class PasswordResetValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PasswordResetLink:
    reset_id: UUID
    token: str = field(repr=False)

    def url(self, public_url: str) -> str:
        return f"{public_url.rstrip('/')}/password-resets/{self.reset_id}#token={self.token}"


class PasswordResetService:
    def __init__(
        self,
        resets: IPasswordResetRepository,
        sessions: ISessionRepository,
        passwords: IPasswordHasher,
    ) -> None:
        self._resets: IPasswordResetRepository = resets
        self._sessions: ISessionRepository = sessions
        self._passwords: IPasswordHasher = passwords

    async def issue(self, email: str, now: datetime) -> PasswordResetLink:
        user = await self._sessions.account_for_update(email)
        if user is None:
            raise UseCaseError(Failure.NOT_FOUND)
        token = secrets.token_urlsafe(32)
        token_hash = supplied_token_hash(token)
        if token_hash is None:
            raise AssertionError("Generated token must be UTF-8 encodable")
        reset_id = await self._resets.issue(user.user_id, token_hash, now, now + RESET_LIFETIME)
        return PasswordResetLink(reset_id, token)

    async def complete(self, reset_id: UUID, token: str, password: str, now: datetime) -> None:
        pending = await self._resets.pending(reset_id)
        if pending is None:
            raise UseCaseError(Failure.LINK_INVALID)
        await self._sessions.lock_account(pending.user_id)
        # Issuance and sign-in lock the same account; re-read after waiting for that lock.
        pending = await self._resets.pending(reset_id)
        token_hash = supplied_token_hash(token)
        if (
            pending is None
            or pending.expires_at <= now
            or token_hash is None
            or not secrets.compare_digest(pending.token_hash, token_hash)
        ):
            raise UseCaseError(Failure.LINK_INVALID)
        if not is_password_strong(password):
            raise PasswordResetValidationError(password_rule_message())
        password_hash = await asyncio.to_thread(self._passwords.hash, password)
        await self._resets.complete(pending.user_id, reset_id, password_hash)


class PasswordResetCleanupService:
    def __init__(self, resets: IPasswordResetRepository) -> None:
        self._resets: IPasswordResetRepository = resets

    async def remove_expired(self, now: datetime) -> int:
        return await self._resets.delete_expired(now)
