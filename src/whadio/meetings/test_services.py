import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..access_policy.models import MeetingAccessGrant
from ..accounts.enums import NotesTemplate, WorkspaceRole
from ..accounts.models import User, Workspace, WorkspaceMembership
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.enums import AuditAction
from ..audit.models import AuditEvent
from ..audit.services import AuditWriter, ContentEvent
from ..shared.database import DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .enums import AccessMode, MeetingSource, ProcessingState, RecordingStatus
from .models import Folder, Meeting
from .repositories import FolderRepository
from .services import FolderService


@asynccontextmanager
async def folder_session(settings: DatabaseSettings) -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(settings.application_url(), hide_parameters=True)
    try:
        async with engine.connect() as connection, connection.begin():
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
            await connection.rollback()
    finally:
        await engine.dispose()


async def populate_folder(session: AsyncSession) -> tuple[UUID, UUID, UUID, UUID, list[UUID]]:
    actor, workspace, source, destination = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    session.add(
        User(
            user_id=actor,
            email=f"{actor}@example.test",
            name="test",
            password_hash=uuid4().hex,
            terms_accepted_at=now,
        )
    )
    session.add(
        Workspace(workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY)
    )
    await session.flush()
    session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=actor, role=WorkspaceRole.OWNER)
    )
    session.add_all(
        [
            Folder(folder_id=source, workspace_id=workspace, name="source"),
            Folder(folder_id=destination, workspace_id=workspace, name="default", is_default=True),
        ]
    )
    await session.flush()
    meetings = [uuid4(), uuid4()]
    for meeting_id in meetings:
        session.add(
            Meeting(
                meeting_id=meeting_id,
                folder_id=source,
                created_by_user_id=actor,
                name="test",
                name_is_generated=False,
                source_type=MeetingSource.UPLOAD,
                recording_status=RecordingStatus.COMPLETE,
                processing_state=ProcessingState.QUEUED,
                access_mode=AccessMode.RESTRICTED,
                recorded_at=now,
                recording_delete_after=now + timedelta(days=90),
            )
        )
    await session.flush()
    for meeting_id in meetings:
        session.add(
            MeetingAccessGrant(meeting_id=meeting_id, user_id=actor, granted_by_user_id=actor)
        )
    await session.flush()
    return actor, workspace, source, destination, meetings


@pytest.mark.slow
def test_folder_deletion_audits_each_move_and_preserves_restricted_grants(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> bool:
        async with folder_session(database_settings) as session:
            actor, workspace, source, destination, meetings = await populate_folder(session)
            service = FolderService(
                FolderRepository(session),
                WorkspaceMembershipService(MembershipRepository(session)),
                AuditWriter(session),
            )
            now = datetime.now(UTC)
            await service.delete_folder(actor, workspace, source, now)
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            events = list(
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.workspace_id == workspace)
                )
            )
            grants = list(
                await session.scalars(
                    select(MeetingAccessGrant.meeting_id).where(
                        MeetingAccessGrant.meeting_id.in_(meetings)
                    )
                )
            )
            locations = list(
                await session.scalars(
                    select(Meeting.folder_id).where(Meeting.meeting_id.in_(meetings))
                )
            )
            return (
                await session.get(Folder, source) is None
                and locations == [destination, destination]
                and set(grants) == set(meetings)
                and len(events) == 2
                and {event.meeting_id for event in events} == set(meetings)
                and all(
                    event.actor_user_id == actor
                    and event.action == AuditAction.MEETING_MOVED
                    and event.occurred_at == now
                    and event.details
                    == {"from_folder_id": str(source), "to_folder_id": str(destination)}
                    for event in events
                )
            )

    # Act
    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result


class FailingAuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._writer: AuditWriter = AuditWriter(session)
        self._written: bool = False

    async def write(self, event: ContentEvent) -> None:
        if self._written:
            raise RuntimeError("Audit unavailable")
        await self._writer.write(event)
        self._written = True


@pytest.mark.slow
def test_audit_failure_rolls_back_folder_moves_and_previous_events(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> bool:
        async with folder_session(database_settings) as session:
            actor, workspace, source, _, meetings = await populate_folder(session)
            service = FolderService(
                FolderRepository(session),
                WorkspaceMembershipService(MembershipRepository(session)),
                FailingAuditWriter(session),
            )
            with pytest.raises(RuntimeError, match="Audit unavailable"):
                async with session.begin_nested():
                    await service.delete_folder(actor, workspace, source, datetime.now(UTC))
            locations = list(
                await session.scalars(
                    select(Meeting.folder_id).where(Meeting.meeting_id.in_(meetings))
                )
            )
            events = list(
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.workspace_id == workspace)
                )
            )
            return (
                locations == [source, source]
                and not events
                and await session.get(Folder, source) is not None
            )

    # Act
    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result


@pytest.mark.slow
@pytest.mark.parametrize("target", ["default", "missing", "outsider", "member"])
def test_folder_deletion_refuses_invalid_target_or_caller(
    database_settings: DatabaseSettings, target: str
) -> None:
    # Arrange
    async def scenario() -> Failure:
        async with folder_session(database_settings) as session:
            actor, workspace, source, destination, _ = await populate_folder(session)
            if target == "member":
                membership = await session.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == workspace,
                        WorkspaceMembership.user_id == actor,
                    )
                )
                assert membership is not None
                membership.role = WorkspaceRole.MEMBER
                await session.flush()
            service = FolderService(
                FolderRepository(session),
                WorkspaceMembershipService(MembershipRepository(session)),
                AuditWriter(session),
            )
            with pytest.raises(UseCaseError) as failure:
                await service.delete_folder(
                    uuid4() if target == "outsider" else actor,
                    workspace,
                    destination
                    if target == "default"
                    else uuid4()
                    if target == "missing"
                    else source,
                    datetime.now(UTC),
                )
            return failure.value.code

    expected = {
        "default": Failure.DEFAULT_FOLDER,
        "missing": Failure.NOT_FOUND,
        "outsider": Failure.NOT_FOUND,
        "member": Failure.INSUFFICIENT_ROLE,
    }[target]
    # Act
    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == expected
