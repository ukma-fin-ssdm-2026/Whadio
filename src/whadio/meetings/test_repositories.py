from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from .enums import AccessMode, ProcessingState
from .models import Meeting
from .repositories import MeetingPipelineRepository, StoredTranscript, TranscriptLine

STORED = StoredTranscript(
    language="uk",
    speakers=("Speaker 1", "Speaker 2"),
    lines=(
        TranscriptLine(Decimal("0.5"), Decimal("2.0"), "Speaker 1", "Привіт"),
        TranscriptLine(Decimal("2.0"), Decimal("3.5"), "Speaker 2", "Добрий день"),
        TranscriptLine(Decimal("4.0"), Decimal("5.0"), None, "шум"),
    ),
)


@pytest.mark.slow
def test_saved_original_transcript_reads_back_unchanged(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> StoredTranscript | None:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place)
        repository = MeetingPipelineRepository(session)
        await repository.save_original_transcript(meeting_id, "parakeet", 62, STORED)
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return await repository.transcript(meeting_id)

    # Act
    stored = async_database.run(scenario)
    # Assert
    assert stored == STORED


@pytest.mark.slow
def test_saved_transcript_sets_the_meeting_duration(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place)
        await MeetingPipelineRepository(session).save_original_transcript(
            meeting_id, "parakeet", 62, STORED
        )
        return await session.scalar(
            select(Meeting.duration_seconds).where(Meeting.meeting_id == meeting_id)
        )

    # Act
    duration = async_database.run(scenario)
    # Assert
    assert duration == 62


@pytest.mark.slow
def test_saved_transcript_is_found(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place)
        repository = MeetingPipelineRepository(session)
        await repository.save_original_transcript(meeting_id, "parakeet", 62, STORED)
        return await repository.has_transcript(meeting_id)

    # Act
    found = async_database.run(scenario)
    # Assert
    assert found


@pytest.mark.slow
def test_summaries_keep_only_the_asked_access_mode(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], UUID]:
        place = await async_database.add_workspace(session)
        open_one = await async_database.add_meeting(session, place, state=ProcessingState.PROCESSED)
        await async_database.add_meeting(
            session, place, state=ProcessingState.PROCESSED, access_mode=AccessMode.RESTRICTED
        )
        summaries = await MeetingPipelineRepository(session).summaries(
            place[1], AccessMode.WORKSPACE, ProcessingState.PROCESSED, 20
        )
        return [summary.meeting_id for summary in summaries], open_one

    # Act
    found, open_one = async_database.run(scenario)
    # Assert
    assert found == [open_one]


@pytest.mark.slow
def test_renamed_meeting_reads_back_its_new_name(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str | None:
        place = await async_database.add_workspace(session)
        meeting_id = await async_database.add_meeting(session, place)
        repository = MeetingPipelineRepository(session)
        await repository.rename(meeting_id, "Sprint planning")
        session.expire_all()
        meeting = await repository.meeting(meeting_id)
        return None if meeting is None else meeting.name

    # Act
    name = async_database.run(scenario)
    # Assert
    assert name == "Sprint planning"
