import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.repositories import MembershipRepository
from ..audit.contracts import ContentEvent
from ..meetings.enums import MeetingSource
from ..meetings.models import Folder, Meeting, RecordingDeletion
from ..meetings.persistence import MeetingPersistence, PersistenceDependencies
from ..meetings.repositories import MeetingRepository
from ..meetings.services import MeetingService, RecordingInput
from ..shared.database import Database, DatabaseSettings

pytestmark = pytest.mark.slow


class AuditFixture:
    async def write(self, event: ContentEvent) -> None:
        del event


def _services(session: AsyncSession, *, hosted_limit: int | None = None) -> MeetingPersistence:
    repository, audit, memberships = (
        MeetingRepository(session),
        AuditFixture(),
        MembershipRepository(session),
    )
    service = MeetingService(
        repository, AccessPolicy(AccessRepository(session), memberships), audit
    )
    return MeetingPersistence(
        PersistenceDependencies(service, repository, memberships, audit),
        hosted_limit=hosted_limit,
    )


def test_concurrent_hosted_ingests_keep_the_owner_within_capacity(
    database_settings: DatabaseSettings,
    committed_workspace: tuple[UUID, UUID],
) -> None:
    # Arrange
    async def scenario() -> None:
        owner, workspace = committed_workspace
        database = Database(database_settings)
        keys: list[str] = []
        try:

            async def ingest() -> None:
                async with database.transaction() as session:
                    now = datetime.now(UTC)
                    key = f"concurrent/{uuid4()}"
                    keys.append(key)
                    await _services(session, hosted_limit=1).ingest(
                        owner, workspace, RecordingInput(key, now, MeetingSource.UPLOAD), now
                    )

            # Act
            await asyncio.wait_for(asyncio.gather(ingest(), ingest()), timeout=10)
            async with database.transaction() as session:
                meetings = list(
                    await session.scalars(
                        select(Meeting.meeting_id)
                        .join(Folder)
                        .where(Folder.workspace_id == workspace)
                    )
                )
            # Assert
            assert len(meetings) == 1
        finally:
            async with database.transaction() as session:
                await session.execute(
                    delete(RecordingDeletion).where(RecordingDeletion.storage_key.in_(keys))
                )
            await database.close()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
