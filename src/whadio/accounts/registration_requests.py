import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .password_resets import AddressMailHistory, PasswordResetMailKind
from .repositories import IRegistrationRepository, ISessionRepository
from .services import REGISTRATION_LIFETIME
from .tokens import generated_token_hash


@dataclass(frozen=True, slots=True)
class RegistrationMail:
    registration_id: UUID
    email: str = field(repr=False)
    issued_at: datetime
    expires_at: datetime


class IRegistrationMailQueue(Protocol):
    async def reserve(self, mail: RegistrationMail, /) -> None:
        """Queue in the caller's transaction; the link gets its token only when the mail is sent."""
        ...

    async def history(self, email: str, now: datetime, /) -> AddressMailHistory:
        """The address's registration, reset and reminder emails, as `IPasswordResetMailQueue`."""
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
        if not (await self._mail.history(email, now)).allows_another(now):
            return
        expires_at = now + REGISTRATION_LIFETIME
        # Nobody learns this token: the mail gets a new one when it is sent.
        unsent_token = secrets.token_urlsafe(32)
        registration_id = await self._registrations.issue(
            email, generated_token_hash(unsent_token), now, expires_at
        )
        await self._mail.reserve(RegistrationMail(registration_id, email, now, expires_at))
