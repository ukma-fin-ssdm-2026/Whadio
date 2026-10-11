import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..accounts.enums import LlmProvider, NotesTemplate, WorkspaceRole
from ..accounts.models import User, Workspace, WorkspaceMembership
from ..shared.database import DatabaseSettings
from .enums import AccessMode, MeetingSource, ProcessingState, RecordingStatus
from .models import Folder, Meeting
from .repositories import (
    GeneratedNotes,
    MeetingPipelineRepository,
    PipelineMeeting,
    StoredTranscript,
    TranscriptLine,
)

STORED = StoredTranscript(
    language="uk",
    speakers=("Speaker 1", "Speaker 2"),
    lines=(
        TranscriptLine(Decimal("0.5"), Decimal("2.0"), "Speaker 1", "Привіт"),
        TranscriptLine(Decimal("2.0"), Decimal("3.5"), "Speaker 2", "Добрий день"),
        TranscriptLine(Decimal("4.0"), Decimal("5.0"), None, "шум"),
    ),
)


@asynccontextmanager
async def rolled_back_session(settings: DatabaseSettings) -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(settings.application_url(), hide_parameters=True)
    try:
        async with engine.connect() as connection, connection.begin():
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
            await connection.rollback()
    finally:
        await engine.dispose()


async def add_meeting(
    session: AsyncSession,
    place: tuple[UUID, UUID],
    *,
    name_is_generated: bool = True,
    access_mode: AccessMode = AccessMode.WORKSPACE,
    state: ProcessingState = ProcessingState.QUEUED,
) -> UUID:
    actor, folder_id = place
    meeting_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        Meeting(
            meeting_id=meeting_id,
            folder_id=folder_id,
            created_by_user_id=actor,
            name="Planning",
            name_is_generated=name_is_generated,
            source_type=MeetingSource.UPLOAD,
            recording_status=RecordingStatus.COMPLETE,
            processing_state=state,
            storage_path=f"meetings/{meeting_id}",
            recorded_at=now,
            recording_delete_after=now + timedelta(days=90),
            access_mode=access_mode,
        )
    )
    await session.flush()
    return meeting_id


async def add_workspace(session: AsyncSession) -> tuple[UUID, UUID]:
    """Returns the actor and the workspace's default folder, where meetings are added."""
    actor, workspace, folder = uuid4(), uuid4(), uuid4()
    session.add(
        User(
            user_id=actor,
            email=f"{actor}@example.test",
            name="test",
            password_hash=uuid4().hex,
            terms_accepted_at=datetime.now(UTC),
        )
    )
    session.add(
        Workspace(workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY)
    )
    await session.flush()
    session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=actor, role=WorkspaceRole.OWNER)
    )
    session.add(Folder(folder_id=folder, workspace_id=workspace, name="default", is_default=True))
    await session.flush()
    return actor, folder


def run_in_session[T](
    settings: DatabaseSettings, scenario: Callable[[AsyncSession], Awaitable[T]]
) -> T:
    async def run() -> T:
        async with rolled_back_session(settings) as session:
            return await scenario(session)

    return asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)


def notes(proposed_name: str) -> GeneratedNotes:
    return GeneratedNotes(
        template=NotesTemplate.SUMMARY,
        provider=LlmProvider.WHADIO,
        model_name="qwen",
        content="## Summary",
        proposed_name=proposed_name,
        context_meeting_ids=(),
    )


@pytest.mark.slow
def test_saved_original_transcript_reads_back_unchanged(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> StoredTranscript | None:
        place = await add_workspace(session)
        meeting_id = await add_meeting(session, place)
        repository = MeetingPipelineRepository(session)
        await repository.save_original_transcript(meeting_id, "parakeet", 62, STORED)
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return await repository.transcript(meeting_id)

    # Act
    stored = run_in_session(database_settings, scenario)
    # Assert
    assert stored == STORED


@pytest.mark.slow
def test_saved_transcript_sets_the_meeting_duration(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        place = await add_workspace(session)
        meeting_id = await add_meeting(session, place)
        await MeetingPipelineRepository(session).save_original_transcript(
            meeting_id, "parakeet", 62, STORED
        )
        return await session.scalar(
            select(Meeting.duration_seconds).where(Meeting.meeting_id == meeting_id)
        )

    # Act
    duration = run_in_session(database_settings, scenario)
    # Assert
    assert duration == 62


@pytest.mark.slow
def test_context_leaves_restricted_meetings_out(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], UUID]:
        place = await add_workspace(session)
        repository = MeetingPipelineRepository(session)
        meeting_id = await add_meeting(session, place)
        open_one = await add_meeting(session, place, state=ProcessingState.PROCESSED)
        restricted = await add_meeting(
            session,
            place,
            state=ProcessingState.PROCESSED,
            access_mode=AccessMode.RESTRICTED,
        )
        for other in (open_one, restricted):
            await repository.save_original_transcript(other, "parakeet", 62, STORED)
        meeting = await repository.meeting(meeting_id)
        if meeting is None:
            return [], open_one
        context = await repository.context(meeting, 20)
        return [candidate.meeting_id for candidate in context], open_one

    # Act
    context, open_one = run_in_session(database_settings, scenario)
    # Assert
    assert context == [open_one]


@pytest.mark.slow
def test_notes_replace_a_generated_name(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> PipelineMeeting | None:
        place = await add_workspace(session)
        meeting_id = await add_meeting(session, place, name_is_generated=True)
        repository = MeetingPipelineRepository(session)
        await repository.save_notes(meeting_id, notes("Sprint planning"))
        session.expire_all()
        return await repository.meeting(meeting_id)

    # Act
    meeting = run_in_session(database_settings, scenario)
    # Assert
    assert (None if meeting is None else meeting.name) == "Sprint planning"


@pytest.mark.slow
def test_notes_keep_a_name_a_member_gave(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> PipelineMeeting | None:
        place = await add_workspace(session)
        meeting_id = await add_meeting(session, place, name_is_generated=False)
        repository = MeetingPipelineRepository(session)
        await repository.save_notes(meeting_id, notes("Sprint planning"))
        session.expire_all()
        return await repository.meeting(meeting_id)

    # Act
    meeting = run_in_session(database_settings, scenario)
    # Assert
    assert (None if meeting is None else meeting.name) == "Planning"
