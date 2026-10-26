import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.errors import HeaderParseError
from email.headerregistry import Address
from typing import Final, Protocol
from uuid import UUID

from pydantic import ValidationError

from .models import LAST_ERROR_LENGTH
from .repositories import IOutboxDrain, OutboxEntry
from .settings import OutboxSettings
from .smtp import IMailSender, MailDeliveryError, OutgoingMail
from .templates import AppLinks, Locale, render

logger = logging.getLogger(__name__)

_ADDRESS_LIKE: Final = re.compile(r"\S+@\S+")


@dataclass(frozen=True, slots=True)
class Recipient:
    name: str
    email: str


class IRecipientDirectory(Protocol):
    async def recipient(self, user_id: UUID, /) -> Recipient | None: ...


@dataclass(frozen=True, slots=True)
class DeliveryUnit:
    outbox: IOutboxDrain
    recipients: IRecipientDirectory


class IDeliveryTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[DeliveryUnit]:
        """Commit on leaving, roll back on an exception."""
        ...


@dataclass(frozen=True, slots=True)
class DrainResult:
    sent: int
    failed: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationDrainer:
    """Sends due notices, each claimed in a transaction of its own that commits first.

    The claim counts the attempt and makes the notice due again only after the sender's longest
    send, so composing or sending a mail that hangs or raises leaves the notice to a later pass
    instead of in front of the others, and a second drainer finds it not due while it is sent.
    The mail is composed and its outcome recorded in later transactions; a failure makes the
    notice due after its backoff instead. Delivery is at least once: a mail is sent again when its
    outcome is not recorded or its send outlasts the longest send.
    """

    def __init__(
        self,
        transactions: IDeliveryTransactions,
        sender: IMailSender,
        links: AppLinks,
        settings: OutboxSettings,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._transactions: IDeliveryTransactions = transactions
        self._sender: IMailSender = sender
        self._links: AppLinks = links
        self._settings: OutboxSettings = settings
        self._now: Callable[[], datetime] = now

    async def drain(self) -> DrainResult:
        sent = failed = 0
        for _ in range(self._settings.batch_size):
            entry = await self._claim()
            if entry is None:
                break
            async with self._transactions.transaction() as unit:
                mail = await self._compose(entry, unit.recipients)
            error = mail if isinstance(mail, str) else await self._send(mail)
            async with self._transactions.transaction() as unit:
                if error is None:
                    await unit.outbox.mark_sent(entry.notice_id, self._now())
                    sent += 1
                    continue
                await unit.outbox.record_failure(
                    entry.notice_id, error, self._now() + self._backoff(entry.attempts)
                )
            failed += 1
            if entry.attempts + 1 >= self._settings.max_attempts:
                logger.warning(
                    "Gave up notice %s (%s) after %d attempts: %s",
                    entry.notice_id,
                    entry.kind,
                    entry.attempts + 1,
                    error,
                )
        return DrainResult(sent, failed)

    async def remove_finished(self) -> int:
        async with self._transactions.transaction() as unit:
            return await unit.outbox.remove_finished(
                self._now() - self._settings.retention, self._settings.max_attempts
            )

    async def _claim(self) -> OutboxEntry | None:
        async with self._transactions.transaction() as unit:
            entry = await unit.outbox.claim_due(self._now(), self._settings.max_attempts)
            if entry is not None:
                await unit.outbox.reschedule(
                    entry.notice_id, self._now() + self._sender.longest_send
                )
            return entry

    async def _compose(
        self, entry: OutboxEntry, recipients: IRecipientDirectory
    ) -> OutgoingMail | str:
        """The mail, or why there is none, naming no address and quoting no content."""
        try:
            notice = entry.notice()
        except ValidationError:
            return "The stored payload does not fit its kind"
        recipient = await recipients.recipient(entry.recipient_id)
        if recipient is None:
            return "The recipient has no account"
        try:
            to = Address(display_name=" ".join(recipient.name.split()), addr_spec=recipient.email)
        except (HeaderParseError, ValueError):
            return "The recipient's address is not valid"
        content = render(notice, self._links, Locale.ENGLISH)
        return OutgoingMail(str(to), content.subject, content.body)

    async def _send(self, mail: OutgoingMail) -> str | None:
        try:
            await asyncio.to_thread(self._sender.send, mail)
        except MailDeliveryError as error:
            return _ADDRESS_LIKE.sub("<address>", str(error))[:LAST_ERROR_LENGTH]
        return None

    def _backoff(self, failures_before: int) -> timedelta:
        delay = self._settings.retry_backoff
        for _ in range(failures_before):
            delay = min(delay * 2, self._settings.max_retry_backoff)
        return delay
