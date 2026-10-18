from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.pagination import ListCursor, ListWindow
from .enums import ShareRequestStatus
from .models import ExternalShare, ShareAccessRequest
from .repositories import AccessRepository

pytestmark = pytest.mark.slow

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
TIED = [UUID(f"00000000-0000-4000-8000-00000000000{digit}") for digit in (2, 3, 1)]


async def add_shares(
    session: AsyncSession, recipient: UUID | None = None
) -> tuple[UUID, list[ExternalShare]]:
    owner, folder = await AsyncDatabase.add_workspace(session)
    meeting = await AsyncDatabase.add_meeting(session, (owner, folder))
    shares = [
        ExternalShare(
            share_id=uuid4(),
            meeting_id=meeting,
            created_by_user_id=owner,
            token_hash=uuid4().hex,
            redact_speaker_names=False,
            created_at=NOW + timedelta(minutes=minute),
            recipient_user_id=recipient,
            revoked_at=None,
        )
        for minute in range(3)
    ]
    session.add_all(shares)
    await session.flush()
    return meeting, shares


def test_shares_page_continues_after_the_cursor(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        meeting, shares = await add_shares(session)
        newest = shares[2]
        cursor = ListCursor(newest.created_at.isoformat(), newest.share_id)
        page = await AccessRepository(session).shares(meeting, ListWindow(1, cursor))
        return [share.share_id for share in page] == [shares[1].share_id]

    # Act
    continued = async_database.run(scenario)
    # Assert
    assert continued


def test_recipient_shares_page_continues_after_the_cursor(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        recipient = (await AsyncDatabase.add_account(session, uuid4().hex)).user_id
        _, shares = await add_shares(session, recipient)
        middle = shares[1]
        cursor = ListCursor(middle.created_at.isoformat(), middle.share_id)
        page = await AccessRepository(session).recipient_shares(recipient, ListWindow(5, cursor))
        return [share.share_id for share in page] == [shares[0].share_id]

    # Act
    continued = async_database.run(scenario)
    # Assert
    assert continued


def test_revoked_shares_are_left_out_of_the_recipient_list(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        recipient = (await AsyncDatabase.add_account(session, uuid4().hex)).user_id
        _, shares = await add_shares(session, recipient)
        shares[2].revoked_at = NOW
        await session.flush()
        page = await AccessRepository(session).recipient_shares(recipient, ListWindow(5))
        return [share.share_id for share in page] == [shares[1].share_id, shares[0].share_id]

    # Act
    listed = async_database.run(scenario)
    # Assert
    assert listed


def test_requests_page_continues_after_the_cursor(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        _, shares = await add_shares(session)
        share_id = shares[0].share_id
        requests = [
            ShareAccessRequest(
                share_access_request_id=uuid4(),
                share_id=share_id,
                requester_user_id=(await AsyncDatabase.add_account(session, uuid4().hex)).user_id,
                status=ShareRequestStatus.PENDING,
                requested_at=NOW + timedelta(minutes=minute),
                decided_at=None,
            )
            for minute in range(3)
        ]
        session.add_all(requests)
        await session.flush()
        newest = requests[2]
        cursor = ListCursor(newest.requested_at.isoformat(), newest.share_access_request_id)
        page = await AccessRepository(session).requests(share_id, ListWindow(5, cursor))
        return [request.share_access_request_id for request in page] == [
            requests[1].share_access_request_id,
            requests[0].share_access_request_id,
        ]

    # Act
    continued = async_database.run(scenario)
    # Assert
    assert continued


# --- Records created at the same moment ---


async def add_tied_shares(session: AsyncSession, recipient: UUID | None = None) -> UUID:
    owner, folder = await AsyncDatabase.add_workspace(session)
    meeting = await AsyncDatabase.add_meeting(session, (owner, folder))
    session.add_all(
        ExternalShare(
            share_id=share_id,
            meeting_id=meeting,
            created_by_user_id=owner,
            token_hash=uuid4().hex,
            redact_speaker_names=False,
            created_at=NOW,
            recipient_user_id=recipient,
            revoked_at=None,
        )
        for share_id in TIED
    )
    await session.flush()
    return meeting


async def page_through[T](
    fetch: Callable[[ListWindow], Awaitable[list[T]]], cursor: Callable[[T], ListCursor]
) -> list[T]:
    found: list[T] = []
    page = await fetch(ListWindow(1))
    for _ in TIED:
        if not page:
            break
        found.extend(page)
        page = await fetch(ListWindow(1, cursor(page[-1])))
    return found


def share_cursor(share: ExternalShare) -> ListCursor:
    return ListCursor(share.created_at.isoformat(), share.share_id)


def test_shares_created_at_the_same_moment_are_paged_without_gaps_or_repeats(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[UUID]:
        meeting = await add_tied_shares(session)
        repository = AccessRepository(session)
        pages = await page_through(lambda window: repository.shares(meeting, window), share_cursor)
        return [share.share_id for share in pages]

    # Act
    listed = async_database.run(scenario)
    # Assert
    assert listed == sorted(TIED, reverse=True)


def test_recipient_shares_created_at_the_same_moment_are_paged_without_gaps_or_repeats(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[UUID]:
        recipient = (await AsyncDatabase.add_account(session, uuid4().hex)).user_id
        await add_tied_shares(session, recipient)
        repository = AccessRepository(session)
        pages = await page_through(
            lambda window: repository.recipient_shares(recipient, window), share_cursor
        )
        return [share.share_id for share in pages]

    # Act
    listed = async_database.run(scenario)
    # Assert
    assert listed == sorted(TIED, reverse=True)


def test_requests_made_at_the_same_moment_are_paged_without_gaps_or_repeats(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[UUID]:
        await add_tied_shares(session)
        share_id = TIED[0]
        session.add_all(
            [
                ShareAccessRequest(
                    share_access_request_id=request_id,
                    share_id=share_id,
                    requester_user_id=(
                        await AsyncDatabase.add_account(session, uuid4().hex)
                    ).user_id,
                    status=ShareRequestStatus.PENDING,
                    requested_at=NOW,
                    decided_at=None,
                )
                for request_id in TIED
            ]
        )
        await session.flush()
        repository = AccessRepository(session)
        pages = await page_through(
            lambda window: repository.requests(share_id, window),
            lambda request: ListCursor(
                request.requested_at.isoformat(), request.share_access_request_id
            ),
        )
        return [request.share_access_request_id for request in pages]

    # Act
    listed = async_database.run(scenario)
    # Assert
    assert listed == sorted(TIED, reverse=True)
