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
from ..meetings.services import MeetingChanges, MeetingService, RecordingInput
from ..shared.database import Database, DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .test_composition import EvictionNotices

pytestmark = pytest.mark.slow


class AuditFixture:
    async def write(self, event: ContentEvent) -> None:
        del event


def _meeting_service(session: AsyncSession) -> MeetingService:
    repository, audit, memberships = (
        MeetingRepository(session),
        AuditFixture(),
        MembershipRepository(session),
    )
    return MeetingService(repository, AccessPolicy(AccessRepository(session), memberships), audit)


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


def test_undo_waits_for_and_refuses_a_concurrent_move(
    database_settings: DatabaseSettings,
    committed_workspace: tuple[UUID, UUID],
) -> None:
    # Arrange
    async def scenario() -> None:
        owner, workspace = committed_workspace
        database = Database(database_settings)
        archive_locked = asyncio.Event()
        undo_started = asyncio.Event()
        try:
            async with database.transaction() as session:
                service = _meeting_service(session)
                original = next(folder for folder in await service.folders(owner, workspace))
                planning = await service.create_folder(
                    owner, workspace, "Planning", datetime.now(UTC)
                )
                archive = await service.create_folder(
                    owner, workspace, "Archive", datetime.now(UTC)
                )
                meeting = await service.create(
                    owner,
                    workspace,
                    RecordingInput(
                        f"concurrent/{uuid4()}", datetime.now(UTC), MeetingSource.UPLOAD
                    ),
                    datetime.now(UTC),
                )
                moved_to_planning = await service.update(
                    owner,
                    meeting.meeting_id,
                    datetime.now(UTC),
                    MeetingChanges(
                        folder_id=planning.folder_id,
                        expected_folder_id=original.folder_id,
                        expected_folder_revision_id=meeting.folder_revision_id,
                    ),
                )

            async def move_to_archive() -> str:
                async with database.transaction() as session:
                    await _meeting_service(session).update(
                        owner,
                        meeting.meeting_id,
                        datetime.now(UTC),
                        MeetingChanges(
                            folder_id=archive.folder_id,
                            expected_folder_id=planning.folder_id,
                            expected_folder_revision_id=moved_to_planning.folder_revision_id,
                        ),
                    )
                    archive_locked.set()
                    await undo_started.wait()
                return "moved"

            async def undo() -> Failure | None:
                await archive_locked.wait()
                async with database.transaction() as session:
                    undo_started.set()
                    try:
                        await _meeting_service(session).update(
                            owner,
                            meeting.meeting_id,
                            datetime.now(UTC),
                            MeetingChanges(
                                folder_id=original.folder_id,
                                expected_folder_id=planning.folder_id,
                                expected_folder_revision_id=moved_to_planning.folder_revision_id,
                            ),
                        )
                    except UseCaseError as error:
                        return error.code
                return None

            # Act
            results = await asyncio.wait_for(asyncio.gather(move_to_archive(), undo()), timeout=10)
            async with database.transaction() as session:
                stored = await _meeting_service(session).get(owner, meeting.meeting_id)
            # Assert
            assert (results, stored.folder_id) == (
                ["moved", Failure.MEETING_MOVE_CONFLICT],
                archive.folder_id,
            )
        finally:
            await database.close()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
