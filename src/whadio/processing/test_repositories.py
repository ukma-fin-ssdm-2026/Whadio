from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from .enums import JobStatus, JobType
from .repositories import Job, JobRepository

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


async def add_job(session: AsyncSession) -> tuple[JobRepository, UUID, UUID]:
    meeting_id = await AsyncDatabase.add_meeting(
        session, await AsyncDatabase.add_workspace(session)
    )
    jobs = JobRepository(session)
    return jobs, meeting_id, await jobs.add(meeting_id, JobType.TRANSCRIPTION)


@pytest.mark.slow
def test_new_job_is_queued_without_attempts(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, _, job_id = await add_job(session)
        return await jobs.lock(job_id)

    # Act
    job = async_database.run(scenario)
    # Assert
    assert (None if job is None else (job.status, job.attempts)) == (JobStatus.QUEUED, 0)


@pytest.mark.slow
def test_running_job_counts_each_start(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, _, job_id = await add_job(session)
        await jobs.mark_running(job_id, NOW)
        await jobs.requeue(job_id)
        await jobs.mark_running(job_id, NOW)
        return await jobs.lock(job_id)

    # Act
    job = async_database.run(scenario)
    # Assert
    assert (None if job is None else (job.status, job.attempts)) == (JobStatus.RUNNING, 2)


@pytest.mark.slow
def test_finished_job_keeps_its_status(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, _, job_id = await add_job(session)
        await jobs.finish(job_id, JobStatus.FAILED, NOW, "unsupported_audio")
        return await jobs.lock(job_id)

    # Act
    job = async_database.run(scenario)
    # Assert
    assert (None if job is None else job.status) is JobStatus.FAILED


@pytest.mark.slow
def test_queued_job_is_unfinished(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        jobs, meeting_id, _ = await add_job(session)
        return await jobs.has_unfinished(meeting_id, JobType.TRANSCRIPTION)

    # Act
    unfinished = async_database.run(scenario)
    # Assert
    assert unfinished


@pytest.mark.slow
def test_succeeded_job_is_not_unfinished(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        jobs, meeting_id, job_id = await add_job(session)
        await jobs.finish(job_id, JobStatus.SUCCEEDED, NOW, None)
        return await jobs.has_unfinished(meeting_id, JobType.TRANSCRIPTION)

    # Act
    unfinished = async_database.run(scenario)
    # Assert
    assert not unfinished
