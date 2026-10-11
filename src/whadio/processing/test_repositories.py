from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ..meetings.test_repositories import add_meeting, add_workspace, run_in_session
from ..shared.database import DatabaseSettings
from .enums import JobStatus, JobType
from .repositories import Job, JobRepository

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


async def add_job(session: AsyncSession) -> tuple[JobRepository, UUID]:
    meeting_id = await add_meeting(session, await add_workspace(session))
    jobs = JobRepository(session)
    return jobs, await jobs.add(meeting_id, JobType.TRANSCRIPTION)


@pytest.mark.slow
def test_new_job_is_queued_without_attempts(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, job_id = await add_job(session)
        return await jobs.lock(job_id)

    # Act
    job = run_in_session(database_settings, scenario)
    # Assert
    assert (None if job is None else (job.status, job.attempts)) == (JobStatus.QUEUED, 0)


@pytest.mark.slow
def test_running_job_counts_each_start(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, job_id = await add_job(session)
        await jobs.mark_running(job_id, NOW)
        await jobs.requeue(job_id)
        await jobs.mark_running(job_id, NOW)
        return await jobs.lock(job_id)

    # Act
    job = run_in_session(database_settings, scenario)
    # Assert
    assert (None if job is None else (job.status, job.attempts)) == (JobStatus.RUNNING, 2)


@pytest.mark.slow
def test_finished_job_keeps_its_status(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        jobs, job_id = await add_job(session)
        await jobs.finish(job_id, JobStatus.FAILED, NOW, "unsupported_audio")
        return await jobs.lock(job_id)

    # Act
    job = run_in_session(database_settings, scenario)
    # Assert
    assert (None if job is None else job.status) is JobStatus.FAILED
