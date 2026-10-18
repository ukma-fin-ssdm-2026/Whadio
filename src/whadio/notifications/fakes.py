import threading
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import override
from uuid import UUID, uuid4

from pydantic import JsonValue

from .repositories import INotificationOutbox, IOutboxDrain, OutboxEntry, notice_payload
from .services import DeliveryUnit, IDeliveryTransactions, IRecipientDirectory, Recipient
from .smtp import IMailSender, OutgoingMail
from .templates import Notice, NoticeKind


class RecordingMailSender(IMailSender):
    def __init__(self, failure: Exception | None = None) -> None:
        self.sent: list[OutgoingMail] = []
        self.caller_threads: set[int] = set()
        self.failure: Exception | None = failure

    @override
    def send(self, mail: OutgoingMail) -> None:
        self.caller_threads.add(threading.get_ident())
        if self.failure is not None:
            raise self.failure
        self.sent.append(mail)


@dataclass(frozen=True, slots=True)
class StoredNotice:
    notice_id: UUID
    recipient_id: UUID
    dedupe_key: str
    kind: NoticeKind
    payload: Mapping[str, JsonValue]
    created_at: datetime
    next_attempt_at: datetime
    attempts: int = 0
    sent_at: datetime | None = None
    last_error: str | None = None


class InMemoryNotificationOutbox(INotificationOutbox, IOutboxDrain):
    def __init__(self, now: Callable[[], datetime]) -> None:
        self.notices: dict[UUID, StoredNotice] = {}
        self._now: Callable[[], datetime] = now

    @override
    async def reserve(self, recipient_id: UUID, dedupe_key: str, notice: Notice) -> None:
        self.store(recipient_id, dedupe_key, notice.kind, notice_payload(notice))

    def store(
        self,
        recipient_id: UUID,
        dedupe_key: str,
        kind: NoticeKind,
        payload: Mapping[str, JsonValue],
    ) -> None:
        """Reserve a notice whose payload is stored as given, valid or not."""
        if any(stored.dedupe_key == dedupe_key for stored in self.notices.values()):
            return
        notice_id, now = uuid4(), self._now()
        self.notices[notice_id] = StoredNotice(
            notice_id, recipient_id, dedupe_key, kind, payload, now, now
        )

    @override
    async def claim_due(self, now: datetime, max_attempts: int) -> OutboxEntry | None:
        due = sorted(
            (
                stored
                for stored in self.notices.values()
                if stored.sent_at is None
                and stored.next_attempt_at <= now
                and stored.attempts < max_attempts
            ),
            key=lambda stored: stored.next_attempt_at,
        )
        if not due:
            return None
        first = due[0]
        return OutboxEntry(
            first.notice_id, first.recipient_id, first.kind, first.payload, first.attempts
        )

    @override
    async def reschedule(self, notice_id: UUID, retry_at: datetime) -> None:
        stored = self.notices[notice_id]
        self.notices[notice_id] = replace(
            stored, attempts=stored.attempts + 1, next_attempt_at=retry_at
        )

    @override
    async def mark_sent(self, notice_id: UUID, sent_at: datetime) -> None:
        self.notices[notice_id] = replace(self.notices[notice_id], sent_at=sent_at, last_error=None)

    @override
    async def record_failure(self, notice_id: UUID, error: str) -> None:
        self.notices[notice_id] = replace(self.notices[notice_id], last_error=error)

    @override
    async def remove_finished(self, before: datetime, max_attempts: int) -> int:
        finished = [
            stored.notice_id
            for stored in self.notices.values()
            if (stored.sent_at is not None and stored.sent_at < before)
            or (
                stored.sent_at is None
                and stored.attempts >= max_attempts
                and stored.created_at < before
            )
        ]
        for notice_id in finished:
            del self.notices[notice_id]
        return len(finished)


class FixedRecipientDirectory(IRecipientDirectory):
    def __init__(
        self,
        recipients: Mapping[UUID, Recipient],
        failures: Mapping[UUID, Exception] | None = None,
    ) -> None:
        self._recipients: Mapping[UUID, Recipient] = recipients
        self._failures: Mapping[UUID, Exception] = failures or {}

    @override
    async def recipient(self, user_id: UUID) -> Recipient | None:
        failure = self._failures.get(user_id)
        if failure is not None:
            raise failure
        return self._recipients.get(user_id)


class InMemoryDeliveryTransactions(IDeliveryTransactions):
    """Restores the outbox when a transaction raises, as the database rolls it back."""

    def __init__(self, outbox: InMemoryNotificationOutbox, recipients: IRecipientDirectory) -> None:
        self._outbox: InMemoryNotificationOutbox = outbox
        self._unit: DeliveryUnit = DeliveryUnit(outbox, recipients)

    @override
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[DeliveryUnit]:
        before = dict(self._outbox.notices)
        try:
            yield self._unit
        except BaseException:
            self._outbox.notices = before
            raise
