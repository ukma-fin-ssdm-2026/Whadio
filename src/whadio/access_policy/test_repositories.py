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
