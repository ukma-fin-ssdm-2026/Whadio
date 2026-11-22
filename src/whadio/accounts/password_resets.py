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
    email: str = field(repr=False)
    reset_id: UUID
    issued_at: datetime
    expires_at: datetime
    kind: PasswordResetMailKind


@dataclass(frozen=True, slots=True)
class AddressMailHistory:
    waiting: bool
    last_sent_at: datetime | None

    def allows_another(self, now: datetime) -> bool:
        """NFR-018: nothing waits to be sent, and the relay took the last one 20 minutes ago."""
        return not self.waiting and (
            self.last_sent_at is None or now >= self.last_sent_at + RESET_MAIL_COOLDOWN
        )


class IPasswordResetMailQueue(Protocol):
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        """Queue in the caller's transaction; the link gets its token only when the mail is sent.

        The reset ID can be reused across issuances, so deduplicate by it and the issue time.
        """
        ...

    async def history(self, email: str, now: datetime, /) -> AddressMailHistory:
        """The address's registration, reset and reminder emails, read in the caller's transaction.

        `waiting` covers only emails whose link has not expired at `now`, and `last_sent_at` is
        when the relay last accepted one.
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
        if not (await self._mail.history(user.email, now)).allows_another(now):
            return
        expires_at = now + RESET_LIFETIME
        # Nobody learns this token: the mail gets a new one when it is sent.
        unsent_token = secrets.token_urlsafe(32)
        reset_id = await self._resets.issue(
            user.user_id, generated_token_hash(unsent_token), now, expires_at
        )
        await self._mail.reserve(
            PasswordResetMail(user.user_id, user.email, reset_id, now, expires_at, kind)
        )


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


@dataclass(frozen=True, slots=True)
class RenewedPasswordReset:
    user_id: UUID
    link: PasswordResetLink


class PasswordResetRenewal:
    def __init__(self, resets: IPasswordResetRepository, sessions: ISessionRepository) -> None:
        self._resets: IPasswordResetRepository = resets
        self._sessions: ISessionRepository = sessions

    async def renew(
        self, reset_id: UUID, issued_at: datetime, now: datetime
    ) -> RenewedPasswordReset | None:
        """Give the link issued at `issued_at` a new token; None once used, reissued or expired."""
        pending = await self._resets.pending(reset_id)
        if pending is None:
            return None
        await self._sessions.lock_account(pending.user_id)
        # Completion and reissue lock the same account; re-read after waiting for that lock.
        pending = await self._resets.pending(reset_id)
        if pending is None or pending.created_at != issued_at or pending.expires_at <= now:
            return None
        token = secrets.token_urlsafe(32)
        await self._resets.replace_token(reset_id, generated_token_hash(token))
        return RenewedPasswordReset(pending.user_id, PasswordResetLink(reset_id, token))


class PasswordResetCleanupService:
    def __init__(self, resets: IPasswordResetRepository) -> None:
        self._resets: IPasswordResetRepository = resets

    async def remove_expired(self, now: datetime) -> int:
        return await self._resets.delete_expired(now)
