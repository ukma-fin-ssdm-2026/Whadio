from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

from pydantic import Field, JsonValue, TypeAdapter
from sqlalchemy import Text, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NotificationOutbox
from .templates import (
    Notice,
    NoticeKind,
    PasswordResetNotice,
    RegistrationLinkNotice,
    SignInReminderNotice,
)

_NOTICE: Final = TypeAdapter[Notice](Annotated[Notice, Field(discriminator="kind")])
_PAYLOAD: Final = TypeAdapter(dict[str, JsonValue])


def notice_payload(notice: Notice) -> dict[str, JsonValue]:
    return _PAYLOAD.validate_python(notice.model_dump(mode="json", exclude={"kind"}))


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    notice_id: UUID
    recipient_id: UUID | None
    kind: NoticeKind
    payload: Mapping[str, JsonValue]
    attempts: int

    def notice(self) -> Notice:
        """Raise ValidationError, whose text repeats the payload, when it no longer fits `kind`."""
        return _NOTICE.validate_python({**self.payload, "kind": self.kind})


@dataclass(frozen=True, slots=True)
class AccountLinkHistory:
    waiting: bool
    last_sent_at: datetime | None


ACCOUNT_LINK_KINDS: Final = frozenset(
    {NoticeKind.REGISTRATION_LINK, NoticeKind.RESET_LINK, NoticeKind.SIGN_IN_REMINDER}
)


def account_link_history(
    notices: Iterable[tuple[NoticeKind, Mapping[str, JsonValue], datetime | None]], now: datetime
) -> AccountLinkHistory:
    """Fold one address's account-link notices, given as kind, payload and `sent_at`."""
    waiting, last_sent_at = False, None
    for kind, payload, sent_at in notices:
        if sent_at is not None:
            last_sent_at = sent_at if last_sent_at is None else max(last_sent_at, sent_at)
            continue
        notice = _NOTICE.validate_python({**payload, "kind": kind})
        if isinstance(notice, RegistrationLinkNotice | PasswordResetNotice | SignInReminderNotice):
            waiting = waiting or notice.expires_at > now
    return AccountLinkHistory(waiting, last_sent_at)


class IAccountLinkHistory(Protocol):
    async def account_link_history(self, address_key: str, now: datetime, /) -> AccountLinkHistory:
        """One address's registration, reset and reminder emails, read in the caller's transaction.

        `waiting` covers unsent ones whose link has not expired at `now`, and `last_sent_at` is
        when the relay last accepted one.
        """
        ...


class INotificationOutbox(Protocol):
    async def reserve(self, recipient_id: UUID | None, dedupe_key: str, notice: Notice, /) -> None:
        """Add the notice in the caller's transaction; a second one with `dedupe_key` is dropped.

        `recipient_id` is None exactly for a registration link, whose address has no account yet.
        """
        ...


class IOutboxDrain(Protocol):
    async def claim_due(self, now: datetime, max_attempts: int, /) -> OutboxEntry | None:
        """Lock the unsent notice due longest, skipping those another transaction holds."""
        ...

    async def reschedule(self, notice_id: UUID, retry_at: datetime, /) -> None:
        """Count an attempt and make the notice due again only at `retry_at`.

        Committed before the mail is sent, it keeps other drainers off the notice once the claim's
        lock is gone, and retries it if the send never reports back.
        """
        ...

    async def mark_sent(self, notice_id: UUID, sent_at: datetime, /) -> None: ...

    async def record_failure(self, notice_id: UUID, error: str, retry_at: datetime, /) -> None: ...

    async def remove_finished(self, before: datetime, max_attempts: int, /) -> int:
        """Delete notices sent before `before`, and given-up ones reserved before it."""
        ...


class NotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def reserve(self, recipient_id: UUID | None, dedupe_key: str, notice: Notice) -> None:
        await self._session.execute(
            insert(NotificationOutbox)
            .values(
                notice_id=uuid4(),
                kind=notice.kind,
                recipient_user_id=recipient_id,
                dedupe_key=dedupe_key,
                payload=notice_payload(notice),
            )
            .on_conflict_do_nothing(index_elements=[NotificationOutbox.dedupe_key])
        )

    async def account_link_history(self, address_key: str, now: datetime) -> AccountLinkHistory:
        notices = await self._session.execute(
            select(
                NotificationOutbox.kind, NotificationOutbox.payload, NotificationOutbox.sent_at
            ).where(
                NotificationOutbox.kind.in_(ACCOUNT_LINK_KINDS),
                func.jsonb_extract_path_text(NotificationOutbox.payload, "address_key", type_=Text)
                == address_key,
            )
        )
        return account_link_history(notices, now)

    async def claim_due(self, now: datetime, max_attempts: int) -> OutboxEntry | None:
        found = await self._session.scalar(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.sent_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
                NotificationOutbox.attempts < max_attempts,
            )
            .order_by(NotificationOutbox.next_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if found is None:
            return None
        return OutboxEntry(
            notice_id=found.notice_id,
            recipient_id=found.recipient_user_id,
            kind=found.kind,
            payload=found.payload,
            attempts=found.attempts,
        )

    async def reschedule(self, notice_id: UUID, retry_at: datetime) -> None:
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.notice_id == notice_id)
            .values(attempts=NotificationOutbox.attempts + 1, next_attempt_at=retry_at)
        )

    async def mark_sent(self, notice_id: UUID, sent_at: datetime) -> None:
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.notice_id == notice_id)
            .values(sent_at=sent_at, last_error=None)
        )

    async def record_failure(self, notice_id: UUID, error: str, retry_at: datetime) -> None:
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.notice_id == notice_id)
            .values(last_error=error, next_attempt_at=retry_at)
        )

    async def remove_finished(self, before: datetime, max_attempts: int) -> int:
        removed = await self._session.scalars(
            delete(NotificationOutbox)
            .where(
                or_(
                    NotificationOutbox.sent_at < before,
                    and_(
                        NotificationOutbox.sent_at.is_(None),
                        NotificationOutbox.attempts >= max_attempts,
                        NotificationOutbox.created_at < before,
                    ),
                )
            )
            .returning(NotificationOutbox.notice_id)
        )
        return len(removed.all())
