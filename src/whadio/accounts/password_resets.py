import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from ..shared.errors import Failure, UseCaseError
from .passwords import IPasswordHasher, is_password_strong, password_rule_message
from .repositories import ISessionRepository
from .reset_repository import IPasswordResetRepository
from .tokens import generated_token_hash, supplied_token_hash

RESET_LIFETIME: Final = timedelta(hours=1)
RESET_MAIL_COOLDOWN: Final = timedelta(minutes=20)


class PasswordResetValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PasswordResetLink:
    reset_id: UUID
    token: str = field(repr=False)

    def url(self, public_url: str) -> str:
        return f"{public_url.rstrip('/')}/password-resets/{self.reset_id}#token={self.token}"


class PasswordResetMailKind(StrEnum):
    RESET = "password_reset"
    SIGN_IN_REMINDER = "sign_in_reminder"


@dataclass(frozen=True, slots=True)
class PasswordResetMail:
    user_id: UUID
    link: PasswordResetLink
    issued_at: datetime
    expires_at: datetime
    kind: PasswordResetMailKind


class IPasswordResetMailQueue(Protocol):
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        """Queue in the caller's transaction. The link ID can be reused across issuances.

        Use the link ID and issuance time for deduplication. Protect the token at rest
        and keep it out of logs.
        """
        ...


async def _issue_link(
    resets: IPasswordResetRepository, user_id: UUID, now: datetime
) -> PasswordResetLink:
    token = secrets.token_urlsafe(32)
    reset_id = await resets.issue(user_id, generated_token_hash(token), now, now + RESET_LIFETIME)
    return PasswordResetLink(reset_id, token)


class PasswordResetRequestService:
    """Issue and reserve mail in the caller's transaction, which must roll back on failure."""

    def __init__(
        self,
        resets: IPasswordResetRepository,
        sessions: ISessionRepository,
        mail: IPasswordResetMailQueue,
        now: Callable[[], datetime],
    ) -> None:
        self._resets: IPasswordResetRepository = resets
        self._sessions: ISessionRepository = sessions
        self._mail: IPasswordResetMailQueue = mail
        self._now: Callable[[], datetime] = now

    async def request(self, email: str, *, kind: PasswordResetMailKind) -> None:
        user = await self._sessions.account_for_update(email)
        if user is None:
            return
        now = self._now()
        queued_at = user.password_reset_mail_queued_at
        if queued_at is not None and now < queued_at + RESET_MAIL_COOLDOWN:
            return
        link = await _issue_link(self._resets, user.user_id, now)
        await self._mail.reserve(
            PasswordResetMail(user.user_id, link, now, now + RESET_LIFETIME, kind)
        )
        await self._resets.mark_mail_queued(user.user_id, self._now())


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
        return await _issue_link(self._resets, user.user_id, now)

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
