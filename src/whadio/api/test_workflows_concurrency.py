import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import BUILT_IN_LLM

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.repositories import MembershipRepository
from ..audit.contracts import ContentEvent
from ..meetings.enums import MeetingSource
from ..meetings.models import Folder, Meeting, RecordingDeletion
from ..meetings.persistence import MeetingPersistence, PersistenceDependencies
from ..meetings.repositories import MeetingRepository
from ..meetings.services import MeetingService, RecordingInput
from ..processing.enums import JobType
from ..processing.models import ProcessingJob
from ..shared.database import Database, DatabaseSettings
from ..shared.errors import UseCaseError
from ..shared.fakes import InMemoryObjectStorage
from .composition import processing_service
from .test_composition import EvictionNotices

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
        PersistenceDependencies(
            service,
            repository,
            memberships,
            audit,
            AccessPolicy(AccessRepository(session), memberships),
            EvictionNotices(),
        ),
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


@pytest.mark.usefixtures("committed_revision_id")
def test_concurrent_regenerations_queue_one_notes_job(
    database_settings: DatabaseSettings, owner_id: UUID, meeting_id: UUID
) -> None:
    # Arrange
    async def scenario() -> tuple[int | None, int | None]:
        database = Database(database_settings)
        try:

            async def regenerate() -> None:
                async with database.transaction() as session:
                    processing = processing_service(
                        session, InMemoryObjectStorage(), BUILT_IN_LLM, 3
                    )
                    with contextlib.suppress(UseCaseError):
                        await processing.queue_notes(
                            meeting_id,
                            owner_id,
                            None,
                            use_builtin_model=False,
                            now=datetime.now(UTC),
                        )

            # Act
            await asyncio.wait_for(asyncio.gather(regenerate(), regenerate()), timeout=10)
            async with database.transaction() as session:
                return (
                    await session.scalar(
                        select(func.count()).where(
                            ProcessingJob.meeting_id == meeting_id,
                            ProcessingJob.job_type == JobType.NOTES,
                        )
                    ),
                    await session.scalar(
                        select(Meeting.regeneration_count).where(Meeting.meeting_id == meeting_id)
                    ),
                )
        finally:
            await database.close()

    counts = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert counts == (1, 1)
