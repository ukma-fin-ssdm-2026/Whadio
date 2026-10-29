import asyncio
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from ..shared.errors import Failure, UseCaseError
from .passwords import IPasswordHasher, is_password_strong
from .reset_repository import IPasswordResetRepository

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
    def __init__(self, resets: IPasswordResetRepository, passwords: IPasswordHasher) -> None:
        self._resets: IPasswordResetRepository = resets
        self._passwords: IPasswordHasher = passwords

    async def issue(self, email: str, now: datetime) -> PasswordResetLink:
        user = await self._resets.account(email)
        if user is None:
            raise UseCaseError(Failure.NOT_FOUND)
        token = secrets.token_urlsafe(32)
        reset_id = await self._resets.issue(
            user.user_id, hashlib.sha256(token.encode()).hexdigest(), now, now + RESET_LIFETIME
        )
        return PasswordResetLink(reset_id, token)

    async def complete(self, reset_id: UUID, token: str, password: str, now: datetime) -> None:
        pending = await self._resets.pending(reset_id)
        if pending is None:
            raise UseCaseError(Failure.LINK_INVALID)
        await self._resets.lock_account(pending.user_id)
        # Issuance and sign-in lock the same account; re-read after waiting for that lock.
        pending = await self._resets.pending(reset_id)
        if (
            pending is None
            or pending.expires_at <= now
            or not secrets.compare_digest(
                pending.token_hash, hashlib.sha256(token.encode()).hexdigest()
            )
        ):
            raise UseCaseError(Failure.LINK_INVALID)
        if not is_password_strong(password):
            raise PasswordResetValidationError(
                "Use 12 to 128 characters, at least one digit and one uppercase letter"
            )
        password_hash = await asyncio.to_thread(self._passwords.hash, password)
        await self._resets.complete(pending.user_id, reset_id, password_hash)
