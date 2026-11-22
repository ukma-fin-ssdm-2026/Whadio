import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from .password_resets import RESET_MAIL_COOLDOWN, PasswordResetMailKind
from .repositories import IRegistrationRepository, ISessionRepository
from .services import REGISTRATION_LIFETIME
from .tokens import generated_token_hash

REGISTRATION_MAIL_COOLDOWN: Final = RESET_MAIL_COOLDOWN


@dataclass(frozen=True, slots=True)
class RegistrationMail:
    registration_id: UUID
    issued_at: datetime
    expires_at: datetime


class IRegistrationMailQueue(Protocol):
    async def reserve(self, mail: RegistrationMail, /) -> None:
        """Queue in the caller's transaction; the link gets its token only when the mail is sent."""
        ...


class IPasswordResetRequests(Protocol):
    async def request(self, email: str, *, kind: PasswordResetMailKind) -> None: ...


class RegistrationRequestService:
    """Issue and queue mail in the caller's transaction, which must roll back on failure."""

    def __init__(
        self,
        registrations: IRegistrationRepository,
        sessions: ISessionRepository,
        resets: IPasswordResetRequests,
        mail: IRegistrationMailQueue,
        now: Callable[[], datetime],
    ) -> None:
        self._registrations: IRegistrationRepository = registrations
        self._sessions: ISessionRepository = sessions
        self._resets: IPasswordResetRequests = resets
        self._mail: IRegistrationMailQueue = mail
        self._now: Callable[[], datetime] = now

    async def request(self, email: str) -> None:
        await self._registrations.lock_email(email)
        if await self._sessions.by_email(email) is not None:
            await self._resets.request(email, kind=PasswordResetMailKind.SIGN_IN_REMINDER)
            return
        now = self._now()
        pending = await self._registrations.pending_for(email)
        if pending is not None and now < pending.created_at + REGISTRATION_MAIL_COOLDOWN:
            return
        expires_at = now + REGISTRATION_LIFETIME
        # Nobody learns this token: the mail gets a new one when it is sent.
        unsent_token = secrets.token_urlsafe(32)
        registration_id = await self._registrations.issue(
            email, generated_token_hash(unsent_token), now, expires_at
        )
        await self._mail.reserve(RegistrationMail(registration_id, now, expires_at))
