import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl

from ..shared.fakes import FixedClock
from .fakes import (
    FixedRecipientDirectory,
    InMemoryDeliveryTransactions,
    InMemoryNotificationOutbox,
    RecordingMailSender,
)
from .services import DrainResult, NotificationDrainer, Recipient
from .settings import OutboxSettings
from .smtp import IMailSender, MailDeliveryError, OutgoingMail
from .templates import AppLinks, Locale, NoticeKind, ProcessingFinished, render

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
RECIPIENT_ID = UUID("3c9d1a52-7b8e-4f61-9a0d-5e2f4b6c8d10")
LINKS = AppLinks(HttpUrl("https://whadio.example.com"))
FINISHED = ProcessingFinished(meeting_id=uuid4(), meeting_name="Weekly sync")
OLENA = Recipient("Olena Koval", "olena@example.com")
LONGEST_SEND = timedelta(minutes=8)
UNREADABLE_RECIPIENT_ID = UUID("9e4f2a61-0c3b-4d7e-8f15-6a2b9c0d1e23")
UNRENDERABLE = ProcessingFinished(
    meeting_id=UUID("5d7c3b19-8a2e-4f60-b1c4-2e9f0a7d6c85"), meeting_name="Weekly sync"
)


@dataclass(frozen=True)
class LinksFailingFor(AppLinks):
    broken_meeting_id: UUID

    @override
    def meeting(self, meeting_id: UUID) -> str:
        if meeting_id == self.broken_meeting_id:
            raise RuntimeError("template bug")
        return AppLinks.meeting(self, meeting_id)


class StalledMailSender(IMailSender):
    def __init__(self) -> None:
        self.sending: threading.Event = threading.Event()
        self.released: threading.Event = threading.Event()

    @property
    @override
    def longest_send(self) -> timedelta:
        return LONGEST_SEND

    @override
    def send(self, mail: OutgoingMail) -> None:
        self.sending.set()
        self.released.wait(timeout=10)


@dataclass
class Delivery:
    clock: FixedClock
    outbox: InMemoryNotificationOutbox
    sender: RecordingMailSender
    drainer: NotificationDrainer

    def drain(self) -> DrainResult:
        return asyncio.run(self.drainer.drain())

    def reserve(
        self,
        dedupe_key: str = "finished",
        recipient_id: UUID = RECIPIENT_ID,
        notice: ProcessingFinished = FINISHED,
    ) -> UUID:
        asyncio.run(self.outbox.reserve(recipient_id, dedupe_key, notice))
        return self.notice_id(dedupe_key)

    def notice_id(self, dedupe_key: str) -> UUID:
        return next(
            stored.notice_id
            for stored in self.outbox.notices.values()
            if stored.dedupe_key == dedupe_key
        )


def delivery(
    *,
    settings: OutboxSettings | None = None,
    failure: Exception | None = None,
    recipient: Recipient | None = OLENA,
) -> Delivery:
    clock = FixedClock(NOW)
    outbox = InMemoryNotificationOutbox(clock)
    sender = RecordingMailSender(LONGEST_SEND, failure)
    directory = FixedRecipientDirectory(
        {} if recipient is None else {RECIPIENT_ID: recipient},
        {UNREADABLE_RECIPIENT_ID: RuntimeError("directory bug")},
    )
    drainer = NotificationDrainer(
        InMemoryDeliveryTransactions(outbox, directory),
        sender,
        LinksFailingFor(LINKS.public_url, UNRENDERABLE.meeting_id),
        settings or OutboxSettings(),
        clock,
    )
    return Delivery(clock, outbox, sender, drainer)


def test_due_notice_is_mailed_to_its_recipient_rendered_from_its_payload() -> None:
    # Arrange
    subject = delivery()
    subject.reserve()
    content = render(FINISHED, LINKS, Locale.ENGLISH)
    # Act
    subject.drain()
    # Assert
    assert subject.sender.sent == [
        OutgoingMail("Olena Koval <olena@example.com>", content.subject, content.body)
    ]


def test_recipient_name_with_a_comma_is_quoted_in_the_address() -> None:
    # Arrange
    subject = delivery(recipient=Recipient("Koval, Olena", "olena@example.com"))
    subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.sender.sent[0].recipient == '"Koval, Olena" <olena@example.com>'


def test_recipient_name_on_several_lines_is_folded_into_one() -> None:
    # Arrange
    subject = delivery(recipient=Recipient("Olena\r\nBcc: eve@example.com", "olena@example.com"))
    subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.sender.sent[0].recipient == '"Olena Bcc: eve@example.com" <olena@example.com>'


def test_mail_is_sent_outside_the_event_loop_thread() -> None:
    # Arrange
    subject = delivery()
    subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert threading.get_ident() not in subject.sender.caller_threads


def test_sent_notice_is_marked_sent_at_the_current_time() -> None:
    # Arrange
    subject = delivery()
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].sent_at == NOW


def test_sent_notice_is_not_mailed_again() -> None:
    # Arrange
    subject = delivery()
    subject.reserve()
    subject.drain()
    # Act
    result = subject.drain()
    # Assert
    assert result == DrainResult(sent=0, failed=0)


def test_failed_delivery_counts_the_attempt_and_waits_the_first_backoff() -> None:
    # Arrange
    subject = delivery(failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"))
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    stored = subject.outbox.notices[notice_id]
    assert (stored.attempts, stored.next_attempt_at, stored.sent_at) == (
        1,
        NOW + timedelta(minutes=1),
        None,
    )


def test_failed_notice_is_not_retried_before_its_backoff_ends() -> None:
    # Arrange
    subject = delivery(failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"))
    subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(seconds=59))
    # Act
    result = subject.drain()
    # Assert
    assert result == DrainResult(sent=0, failed=0)


def test_notice_still_being_sent_after_its_backoff_is_not_sent_by_a_second_drainer() -> None:
    # Arrange
    clock = FixedClock(NOW)
    outbox = InMemoryNotificationOutbox(clock)
    transactions = InMemoryDeliveryTransactions(
        outbox, FixedRecipientDirectory({RECIPIENT_ID: OLENA})
    )
    stalled = StalledMailSender()
    first = NotificationDrainer(transactions, stalled, LINKS, OutboxSettings(), clock)
    second = NotificationDrainer(
        transactions, RecordingMailSender(LONGEST_SEND), LINKS, OutboxSettings(), clock
    )
    asyncio.run(outbox.reserve(RECIPIENT_ID, "finished", FINISHED))

    async def scenario() -> DrainResult:
        first_pass = asyncio.create_task(first.drain())
        await asyncio.to_thread(stalled.sending.wait, 10)
        clock.advance(OutboxSettings().retry_backoff + timedelta(seconds=1))
        # Act
        result = await second.drain()
        stalled.released.set()
        await first_pass
        return result

    result = asyncio.run(scenario())
    # Assert
    assert result == DrainResult(sent=0, failed=0)


def test_backoff_doubles_with_each_failure_up_to_its_cap() -> None:
    # Arrange
    subject = delivery(
        settings=OutboxSettings(
            retry_backoff=timedelta(minutes=1), max_retry_backoff=timedelta(minutes=5)
        ),
        failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"),
    )
    notice_id = subject.reserve()
    waits: list[timedelta] = []
    # Act
    for _ in range(5):
        subject.drain()
        retry_at = subject.outbox.notices[notice_id].next_attempt_at
        waits.append(retry_at - subject.clock())
        subject.clock.advance(retry_at - subject.clock())
    # Assert
    assert waits == [timedelta(minutes=minutes) for minutes in (1, 2, 4, 5, 5)]


def test_notice_that_used_up_its_attempts_is_given_up() -> None:
    # Arrange
    subject = delivery(
        settings=OutboxSettings(max_attempts=2),
        failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"),
    )
    subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(days=1))
    subject.drain()
    subject.clock.advance(timedelta(days=1))
    # Act
    result = subject.drain()
    # Assert
    assert result == DrainResult(sent=0, failed=0)


def test_failed_delivery_stores_the_error_with_addresses_masked() -> None:
    # Arrange
    subject = delivery(
        failure=MailDeliveryError("Relay refused olena@example.com from whadio@localhost")
    )
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].last_error == "Relay refused <address> from <address>"


def test_unexpected_sender_error_leaves_the_notice_due_after_the_longest_send() -> None:
    # Arrange
    subject = delivery(failure=RuntimeError("sender bug"))
    notice_id = subject.reserve()
    # Act
    with pytest.raises(RuntimeError):
        subject.drain()
    # Assert
    stored = subject.outbox.notices[notice_id]
    assert (stored.attempts, stored.next_attempt_at, stored.sent_at) == (
        1,
        NOW + LONGEST_SEND,
        None,
    )


def test_notice_whose_send_raised_does_not_block_the_next_one() -> None:
    # Arrange
    subject = delivery(failure=RuntimeError("sender bug"))
    subject.reserve("first")
    second = subject.reserve("second")
    with pytest.raises(RuntimeError):
        subject.drain()
    subject.sender.failure = None
    # Act
    subject.drain()
    # Assert
    sent = {notice_id for notice_id, stored in subject.outbox.notices.items() if stored.sent_at}
    assert sent == {second}


COMPOSE_FAILURES = [
    pytest.param(UNREADABLE_RECIPIENT_ID, FINISHED, id="recipient-lookup"),
    pytest.param(RECIPIENT_ID, UNRENDERABLE, id="rendering"),
]


@pytest.mark.parametrize(("recipient_id", "notice"), COMPOSE_FAILURES)
def test_unexpected_error_while_composing_leaves_the_notice_due_after_the_longest_send(
    recipient_id: UUID, notice: ProcessingFinished
) -> None:
    # Arrange
    subject = delivery()
    notice_id = subject.reserve("broken", recipient_id, notice)
    # Act
    with pytest.raises(RuntimeError):
        subject.drain()
    # Assert
    stored = subject.outbox.notices[notice_id]
    assert (stored.attempts, stored.next_attempt_at, stored.sent_at) == (
        1,
        NOW + LONGEST_SEND,
        None,
    )


@pytest.mark.parametrize(("recipient_id", "notice"), COMPOSE_FAILURES)
def test_notice_whose_mail_could_not_be_composed_does_not_block_the_next_one(
    recipient_id: UUID, notice: ProcessingFinished
) -> None:
    # Arrange
    subject = delivery()
    subject.reserve("broken", recipient_id, notice)
    second = subject.reserve("second")
    with pytest.raises(RuntimeError):
        subject.drain()
    # Act
    subject.drain()
    # Assert
    sent = {notice_id for notice_id, stored in subject.outbox.notices.items() if stored.sent_at}
    assert sent == {second}


def test_sent_notice_drops_the_error_of_an_earlier_attempt() -> None:
    # Arrange
    subject = delivery(failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"))
    notice_id = subject.reserve()
    subject.drain()
    subject.sender.failure = None
    subject.clock.advance(timedelta(minutes=1))
    # Act
    subject.drain()
    # Assert
    stored = subject.outbox.notices[notice_id]
    assert (stored.sent_at, stored.last_error, stored.attempts) == (
        NOW + timedelta(minutes=1),
        None,
        2,
    )


def test_stored_error_is_capped_at_the_column_length() -> None:
    # Arrange
    subject = delivery(failure=MailDeliveryError("x" * 500))
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].last_error == "x" * 200


def test_stored_payload_that_no_longer_fits_its_kind_fails_without_quoting_it() -> None:
    # Arrange
    subject = delivery()
    subject.outbox.store(
        RECIPIENT_ID, "broken", NoticeKind.PROCESSING_FINISHED, {"meeting_name": "Secret plans"}
    )
    notice_id = subject.notice_id("broken")
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].last_error == (
        "The stored payload does not fit its kind"
    )


def test_notice_for_a_missing_account_fails() -> None:
    # Arrange
    subject = delivery(recipient=None)
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].last_error == "The recipient has no account"


def test_notice_for_an_invalid_address_fails_without_sending() -> None:
    # Arrange
    subject = delivery(recipient=Recipient("Olena", "olena@example.com\nBcc: eve@example.com"))
    notice_id = subject.reserve()
    # Act
    subject.drain()
    # Assert
    assert subject.outbox.notices[notice_id].last_error == "The recipient's address is not valid"


def test_one_pass_sends_at_most_the_batch_size() -> None:
    # Arrange
    subject = delivery(settings=OutboxSettings(batch_size=2))
    for key in ("first", "second", "third"):
        subject.reserve(key)
    # Act
    result = subject.drain()
    # Assert
    assert result == DrainResult(sent=2, failed=0)


def test_pass_counts_the_failed_deliveries() -> None:
    # Arrange
    subject = delivery(failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"))
    for key in ("first", "second"):
        subject.reserve(key)
    # Act
    result = subject.drain()
    # Assert
    assert result == DrainResult(sent=0, failed=2)


def test_notice_sent_longer_ago_than_the_retention_is_removed() -> None:
    # Arrange
    subject = delivery(settings=OutboxSettings(retention=timedelta(days=7)))
    subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(days=7, seconds=1))
    # Act
    asyncio.run(subject.drainer.remove_finished())
    # Assert
    assert subject.outbox.notices == {}


def test_notice_sent_within_the_retention_is_kept() -> None:
    # Arrange
    subject = delivery(settings=OutboxSettings(retention=timedelta(days=7)))
    notice_id = subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(days=7))
    # Act
    asyncio.run(subject.drainer.remove_finished())
    # Assert
    assert list(subject.outbox.notices) == [notice_id]


def test_unsent_notice_still_retried_is_kept_past_the_retention() -> None:
    # Arrange
    subject = delivery(
        settings=OutboxSettings(retention=timedelta(days=1)),
        failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"),
    )
    notice_id = subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(days=2))
    # Act
    asyncio.run(subject.drainer.remove_finished())
    # Assert
    assert list(subject.outbox.notices) == [notice_id]


def test_given_up_notice_is_removed_once_reserved_longer_ago_than_the_retention() -> None:
    # Arrange
    subject = delivery(
        settings=OutboxSettings(max_attempts=1, retention=timedelta(days=1)),
        failure=MailDeliveryError("SMTP delivery failed: SMTPServerDisconnected"),
    )
    subject.reserve()
    subject.drain()
    subject.clock.advance(timedelta(days=1, seconds=1))
    # Act
    asyncio.run(subject.drainer.remove_finished())
    # Assert
    assert subject.outbox.notices == {}
