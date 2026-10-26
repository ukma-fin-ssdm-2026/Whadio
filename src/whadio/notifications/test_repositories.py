import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import Boolean, func, literal_column, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from conftest import AsyncDatabase

from ..shared.database import DatabaseSettings
from .models import NotificationOutbox
from .repositories import NotificationOutboxRepository, OutboxEntry, notice_payload
from .templates import HostedEviction, ProcessingFinished

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FINISHED = ProcessingFinished(meeting_id=uuid4(), meeting_name="Weekly sync")
EVICTION = HostedEviction(meeting_name=None)


def soon() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=1)


async def only_new_notices_unsent(session: AsyncSession) -> None:
    # The development database may hold unsent notices; the rollback restores them.
    await session.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.sent_at.is_(None))
        .values(sent_at=LONG_AGO)
    )


async def reserve(session: AsyncSession, key: str, notice: ProcessingFinished) -> UUID:
    recipient, _ = await AsyncDatabase.add_workspace(session)
    await NotificationOutboxRepository(session).reserve(recipient, key, notice)
    return await notice_id(session, key)


async def notice_id(session: AsyncSession, key: str) -> UUID:
    found = await session.scalar(
        select(NotificationOutbox.notice_id).where(NotificationOutbox.dedupe_key == key)
    )
    if found is None:
        raise LookupError(key)
    return found


async def stored(session: AsyncSession, notice: UUID) -> NotificationOutbox:
    row = await session.get(NotificationOutbox, notice, populate_existing=True)
    if row is None:
        raise LookupError(notice)
    return row


@pytest.mark.slow
def test_second_reservation_with_the_same_dedupe_key_is_dropped(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    key = f"test:{uuid4()}"

    async def scenario(session: AsyncSession) -> list[dict[str, JsonValue]]:
        recipient, _ = await AsyncDatabase.add_workspace(session)
        outbox = NotificationOutboxRepository(session)
        await outbox.reserve(recipient, key, FINISHED)
        # Act
        await outbox.reserve(recipient, key, EVICTION)
        rows = await session.scalars(
            select(NotificationOutbox.payload).where(NotificationOutbox.dedupe_key == key)
        )
        return list(rows)

    payloads = async_database.run(scenario)
    # Assert
    assert payloads == [notice_payload(FINISHED)]


@pytest.mark.slow
def test_reserved_notice_is_claimed_as_it_was_reserved(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[OutboxEntry | None, UUID]:
        await only_new_notices_unsent(session)
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        # Act
        return await NotificationOutboxRepository(session).claim_due(soon(), 16), notice

    entry, notice = async_database.run(scenario)
    # Assert
    assert (None if entry is None else (entry.notice_id, entry.notice(), entry.attempts)) == (
        notice,
        FINISHED,
        0,
    )


@pytest.mark.slow
def test_notice_due_later_is_not_claimed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> OutboxEntry | None:
        await only_new_notices_unsent(session)
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        outbox = NotificationOutboxRepository(session)
        await outbox.reschedule(notice, soon() + timedelta(hours=1))
        # Act
        return await outbox.claim_due(soon(), 16)

    entry = async_database.run(scenario)
    # Assert
    assert entry is None


@pytest.mark.slow
def test_sent_notice_is_not_claimed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> OutboxEntry | None:
        await only_new_notices_unsent(session)
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        outbox = NotificationOutboxRepository(session)
        await outbox.mark_sent(notice, datetime.now(UTC))
        # Act
        return await outbox.claim_due(soon(), 16)

    entry = async_database.run(scenario)
    # Assert
    assert entry is None


@pytest.mark.slow
def test_notice_that_used_up_its_attempts_is_not_claimed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> OutboxEntry | None:
        await only_new_notices_unsent(session)
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        outbox = NotificationOutboxRepository(session)
        await outbox.reschedule(notice, LONG_AGO)
        # Act
        return await outbox.claim_due(soon(), 1)

    entry = async_database.run(scenario)
    # Assert
    assert entry is None


@pytest.mark.slow
def test_rescheduled_notice_counts_the_attempt_and_is_due_at_the_retry_time(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    retry_at = datetime(2026, 10, 19, 12, 5, tzinfo=UTC)

    async def scenario(session: AsyncSession) -> tuple[int, datetime]:
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        # Act
        await NotificationOutboxRepository(session).reschedule(notice, retry_at)
        row = await stored(session, notice)
        return row.attempts, row.next_attempt_at

    found = async_database.run(scenario)
    # Assert
    assert found == (1, retry_at)


@pytest.mark.slow
def test_failure_stores_the_error_and_is_due_at_the_retry_time(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    retry_at = datetime(2026, 10, 19, 12, 5, tzinfo=UTC)

    async def scenario(session: AsyncSession) -> tuple[str | None, datetime]:
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        # Act
        await NotificationOutboxRepository(session).record_failure(
            notice, "SMTPServerDisconnected", retry_at
        )
        row = await stored(session, notice)
        return row.last_error, row.next_attempt_at

    found = async_database.run(scenario)
    # Assert
    assert found == ("SMTPServerDisconnected", retry_at)


@pytest.mark.slow
def test_sent_notice_records_when_it_was_sent_and_drops_an_earlier_error(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    sent_at = datetime(2026, 10, 19, 12, 5, tzinfo=UTC)

    async def scenario(session: AsyncSession) -> tuple[datetime | None, str | None]:
        notice = await reserve(session, f"test:{uuid4()}", FINISHED)
        outbox = NotificationOutboxRepository(session)
        await outbox.record_failure(notice, "SMTPServerDisconnected", soon())
        # Act
        await outbox.mark_sent(notice, sent_at)
        row = await stored(session, notice)
        return row.sent_at, row.last_error

    found = async_database.run(scenario)
    # Assert
    assert found == (sent_at, None)


@pytest.mark.slow
def test_cleanup_removes_notices_sent_and_given_up_before_the_cutoff(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    now = datetime.now(UTC)
    prefix = f"test:{uuid4()}"

    async def scenario(session: AsyncSession) -> set[str]:
        outbox = NotificationOutboxRepository(session)
        sent_long_ago = await reserve(session, f"{prefix}:sent-long-ago", FINISHED)
        await outbox.mark_sent(sent_long_ago, now - timedelta(days=2))
        sent_later = await reserve(session, f"{prefix}:sent-later", FINISHED)
        await outbox.mark_sent(sent_later, now + timedelta(days=2))
        retrying = await reserve(session, f"{prefix}:retrying", FINISHED)
        await outbox.reschedule(retrying, now)
        given_up = await reserve(session, f"{prefix}:given-up", FINISHED)
        await outbox.reschedule(given_up, now)
        await outbox.reschedule(given_up, now)
        # Act
        await outbox.remove_finished(now + timedelta(days=1), 2)
        rows = await session.scalars(
            select(NotificationOutbox.dedupe_key).where(
                NotificationOutbox.dedupe_key.startswith(prefix)
            )
        )
        return set(rows)

    remaining = async_database.run(scenario)
    # Assert
    assert remaining == {f"{prefix}:sent-later", f"{prefix}:retrying"}


@pytest.mark.slow
def test_deleting_the_recipient_deletes_their_notices(async_database: AsyncDatabase) -> None:
    # Arrange
    key = f"test:{uuid4()}"

    async def scenario(session: AsyncSession) -> int | None:
        recipient = await AsyncDatabase.add_account(session, "correct horse battery")
        await NotificationOutboxRepository(session).reserve(recipient.user_id, key, FINISHED)
        # Act
        await session.execute(
            text('DELETE FROM "user" WHERE user_id = :id'), {"id": recipient.user_id}
        )
        return await session.scalar(
            select(func.count()).where(NotificationOutbox.dedupe_key == key)
        )

    count = async_database.run(scenario)
    # Assert
    assert count == 0


@pytest.mark.slow
def test_payload_that_is_not_an_object_is_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> None:
        recipient, _ = await AsyncDatabase.add_workspace(session)
        # Act
        await session.execute(
            text(
                "INSERT INTO notification_outbox (notice_id, kind, recipient_user_id, dedupe_key, "
                "payload) VALUES (:id, 'hosted_eviction', :recipient, :key, '[]')"
            ),
            {"id": uuid4(), "recipient": recipient, "key": f"test:{uuid4()}"},
        )

    # Assert
    with pytest.raises(IntegrityError, match="ck_notification_outbox_payload"):
        async_database.run(scenario)


async def has_outbox_privilege(session: AsyncSession, privilege: str) -> bool | None:
    return await session.scalar(
        select(
            func.has_table_privilege(
                literal_column("current_user"), "notification_outbox", privilege, type_=Boolean
            )
        )
    )


@pytest.mark.slow
@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_application_role_reads_and_writes_outbox_rows(
    async_database: AsyncDatabase, privilege: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool | None:
        # Act
        return await has_outbox_privilege(session, privilege)

    found = async_database.run(scenario)
    # Assert
    assert found is True


@pytest.mark.slow
@pytest.mark.parametrize("privilege", ["TRUNCATE", "REFERENCES", "TRIGGER"])
def test_application_role_holds_no_table_level_privilege_on_the_outbox(
    async_database: AsyncDatabase, privilege: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool | None:
        # Act
        return await has_outbox_privilege(session, privilege)

    found = async_database.run(scenario)
    # Assert
    assert found is False


async def claims_side_by_side(
    settings: DatabaseSettings, recipient: UUID, key: str
) -> tuple[UUID, UUID | None, UUID | None]:
    engine = create_async_engine(settings.application_url(), hide_parameters=True)
    try:
        async with AsyncSession(engine) as setup, setup.begin():
            await NotificationOutboxRepository(setup).reserve(recipient, key, FINISHED)
            await setup.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.dedupe_key == key)
                .values(next_attempt_at=LONG_AGO)
            )
            reserved = await notice_id(setup, key)
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            held = await NotificationOutboxRepository(first).claim_due(soon(), 16)
            # A claim that waited for the lock would hang the test instead of failing it.
            await second.execute(text("SET LOCAL lock_timeout = '2s'"))
            other = await NotificationOutboxRepository(second).claim_due(soon(), 16)
        return (
            reserved,
            None if held is None else held.notice_id,
            None if other is None else other.notice_id,
        )
    finally:
        await engine.dispose()


@pytest.mark.slow
def test_notice_claimed_by_one_transaction_is_skipped_by_another(
    database_settings: DatabaseSettings, committed_workspace: tuple[UUID, UUID]
) -> None:
    # Arrange
    recipient, _ = committed_workspace
    # Act
    reserved, held, other = asyncio.run(
        claims_side_by_side(database_settings, recipient, f"test:{uuid4()}"),
        loop_factory=asyncio.SelectorEventLoop,
    )
    # Assert
    assert (held, other == reserved) == (reserved, False)
