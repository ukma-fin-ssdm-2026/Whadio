import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from conftest import AsyncDatabase

from ..access_policy.models import MeetingAccessGrant
from ..accounts.enums import LlmProvider, NotesTemplate, WorkspaceRole
from ..accounts.models import User, Workspace, WorkspaceMembership
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.enums import AuditAction
from ..audit.models import AuditEvent
from ..audit.services import AuditWriter, MeetingMoved
from ..shared.database import DatabaseSettings
from .enums import AccessMode, MeetingSource, ProcessingState, RecordingStatus
from .models import Folder, Meeting
from .repositories import FolderRepository, GeneratedNotes, MeetingPipelineRepository
from .services import FolderService, MeetingPipelineService


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


@dataclass(frozen=True)
class AuditState:
    actor_id: UUID
    action: AuditAction
    workspace_id: UUID | None
    meeting_id: UUID | None
    occurred_at: datetime
    details: JsonValue | None


@dataclass(frozen=True)
class FolderState:
    source_exists: bool
    locations: tuple[UUID, ...]
    grants: frozenset[UUID]
    events: tuple[AuditState, ...]


@dataclass(frozen=True)
class RollbackState:
    source_exists: bool
    locations: tuple[UUID, ...]
    event_count: int


@pytest.mark.slow
def test_folder_deletion_audits_each_move_and_preserves_restricted_grants(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[FolderState, FolderState]:
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
            observed = FolderState(
                source_exists=await session.get(Folder, source) is not None,
                locations=tuple(locations),
                grants=frozenset(grants),
                events=tuple(
                    AuditState(
                        event.actor_user_id,
                        event.action,
                        event.workspace_id,
                        event.meeting_id,
                        event.occurred_at,
                        event.details,
                    )
                    for event in sorted(events, key=lambda event: str(event.meeting_id))
                ),
            )
            expected = FolderState(
                source_exists=False,
                locations=(destination, destination),
                grants=frozenset(meetings),
                events=tuple(
                    AuditState(
                        actor,
                        AuditAction.MEETING_MOVED,
                        workspace,
                        meeting_id,
                        now,
                        {"from_folder_id": str(source), "to_folder_id": str(destination)},
                    )
                    for meeting_id in sorted(meetings, key=str)
                ),
            )
            return observed, expected

    # Act
    observed, expected = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert observed == expected


class FailingAuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._writer: AuditWriter = AuditWriter(session)
        self._written: bool = False

    async def write(self, event: MeetingMoved) -> None:
        if self._written:
            raise RuntimeError("Audit unavailable")
        await self._writer.write(event)
        self._written = True


@pytest.mark.slow
def test_audit_failure_rolls_back_folder_moves_and_previous_events(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[RollbackState, RollbackState]:
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
                RollbackState(
                    source_exists=await session.get(Folder, source) is not None,
                    locations=tuple(locations),
                    event_count=len(events),
                ),
                RollbackState(source_exists=True, locations=(source, source), event_count=0),
            )

    # Act
    observed, expected = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert observed == expected


# --- The meeting pipeline ---


def generated_notes(proposed_name: str) -> GeneratedNotes:
    return GeneratedNotes(
        template=NotesTemplate.SUMMARY,
        provider=LlmProvider.WHADIO,
        model_name="qwen",
        content="## Summary",
        proposed_name=proposed_name,
        context=(),
    )


async def saved_name(session: AsyncSession, meeting_id: UUID, proposed_name: str) -> str | None:
    pipeline = MeetingPipelineService(MeetingPipelineRepository(session))
    meeting = await pipeline.lock(meeting_id)
    if meeting is None:
        return None
    await pipeline.save_notes(meeting, generated_notes(proposed_name))
    session.expire_all()
    renamed = await pipeline.meeting(meeting_id)
    return None if renamed is None else renamed.name


@pytest.mark.slow
def test_context_leaves_restricted_meetings_out(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], UUID]:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place)
        open_one = await async_database.add_meeting(session, place, state=ProcessingState.PROCESSED)
        await async_database.add_meeting(
            session, place, state=ProcessingState.PROCESSED, access_mode=AccessMode.RESTRICTED
        )
        pipeline = MeetingPipelineService(MeetingPipelineRepository(session))
        meeting = await pipeline.meeting(meeting_id)
        if meeting is None:
            return [], open_one
        summaries = await pipeline.context_summaries(meeting, 20)
        return [summary.meeting_id for summary in summaries], open_one

    # Act
    context, open_one = async_database.run(scenario)
    # Assert
    assert context == [open_one]


@pytest.mark.slow
def test_context_leaves_the_meeting_itself_out(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[UUID]:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(
            session, place, state=ProcessingState.PROCESSED
        )
        pipeline = MeetingPipelineService(MeetingPipelineRepository(session))
        meeting = await pipeline.meeting(meeting_id)
        if meeting is None:
            return [meeting_id]
        return [summary.meeting_id for summary in await pipeline.context_summaries(meeting, 20)]

    # Act
    context = async_database.run(scenario)
    # Assert
    assert context == []


@pytest.mark.slow
def test_notes_replace_a_generated_name(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str | None:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place, name_is_generated=True)
        return await saved_name(session, meeting_id, "Sprint planning")

    # Act
    name = async_database.run(scenario)
    # Assert
    assert name == "Sprint planning"


@pytest.mark.slow
def test_notes_keep_a_name_a_member_gave(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str | None:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place, name_is_generated=False)
        return await saved_name(session, meeting_id, "Sprint planning")

    # Act
    name = async_database.run(scenario)
    # Assert
    assert name == "Planning"
