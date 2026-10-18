from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

from pydantic import Field, JsonValue, TypeAdapter
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NotificationOutbox
from .templates import Notice, NoticeKind

_NOTICE: Final = TypeAdapter[Notice](Annotated[Notice, Field(discriminator="kind")])
_PAYLOAD: Final = TypeAdapter(dict[str, JsonValue])


def notice_payload(notice: Notice) -> dict[str, JsonValue]:
    return _PAYLOAD.validate_python(notice.model_dump(mode="json", exclude={"kind"}))


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    notice_id: UUID
    recipient_id: UUID
    kind: NoticeKind
    payload: Mapping[str, JsonValue]
    attempts: int

    def notice(self) -> Notice:
        """Raise ValidationError, whose text repeats the payload, when it no longer fits `kind`."""
        return _NOTICE.validate_python({**self.payload, "kind": self.kind})


class INotificationOutbox(Protocol):
    async def reserve(self, recipient_id: UUID, dedupe_key: str, notice: Notice, /) -> None:
        """Add the notice in the caller's transaction; a second one with `dedupe_key` is dropped."""
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

    async def record_failure(self, notice_id: UUID, error: str, /) -> None: ...

    async def remove_finished(self, before: datetime, max_attempts: int, /) -> int:
        """Delete notices sent before `before`, and given-up ones reserved before it."""
        ...


class NotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def reserve(self, recipient_id: UUID, dedupe_key: str, notice: Notice) -> None:
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

    async def record_failure(self, notice_id: UUID, error: str) -> None:
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.notice_id == notice_id)
            .values(last_error=error)
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
