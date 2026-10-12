from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..meetings.contracts import ContextReference
from .enums import JobStatus, JobType
from .models import ProcessingJob
from .repositories import Job, JobRepository

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


async def add_job(session: AsyncSession) -> tuple[JobRepository, UUID, UUID]:
    meeting_id = await AsyncDatabase.add_meeting(
        session, await AsyncDatabase.add_workspace(session)
    )
    jobs = JobRepository(session)
    return jobs, meeting_id, await jobs.add(meeting_id, JobType.TRANSCRIPTION)


async def only_new_jobs_unpublished(session: AsyncSession) -> None:
    # The development database may hold unpublished jobs; the rollback restores them.
    await session.execute(
        update(ProcessingJob).where(ProcessingJob.published_at.is_(None)).values(published_at=NOW)
    )


@pytest.mark.slow
def test_new_job_is_unpublished(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID | None, UUID]:
        await only_new_jobs_unpublished(session)
        jobs, _, job_id = await add_job(session)
        # Act
        found = await jobs.next_unpublished()
        return None if found is None else found.job_id, job_id

    found, job_id = async_database.run(scenario)
    # Assert
    assert found == job_id


@pytest.mark.slow
def test_published_job_is_not_unpublished(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Job | None:
        await only_new_jobs_unpublished(session)
        jobs, _, job_id = await add_job(session)
        # Act
        await jobs.mark_published(job_id, NOW, ())
        return await jobs.next_unpublished()

    found = async_database.run(scenario)
    # Assert
    assert found is None


@pytest.mark.slow
def test_requeued_job_is_unpublished_again(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID | None, UUID]:
        await only_new_jobs_unpublished(session)
        jobs, _, job_id = await add_job(session)
        await jobs.mark_published(job_id, NOW, ())
        await jobs.mark_running(job_id, NOW)
        # Act
        await jobs.requeue(job_id)
        found = await jobs.next_unpublished()
        return None if found is None else found.job_id, job_id

    found, job_id = async_database.run(scenario)
    # Assert
    assert found == job_id


@pytest.mark.slow
def test_published_job_keeps_the_context_it_was_sent(async_database: AsyncDatabase) -> None:
    # Arrange
    sent = (ContextReference(uuid4(), "Earlier sync"),)

    async def scenario(session: AsyncSession) -> Job | None:
        jobs, _, job_id = await add_job(session)
        # Act
        await jobs.mark_published(job_id, NOW, sent)
        return await jobs.lock(job_id)

    job = async_database.run(scenario)
    # Assert
    assert (None if job is None else job.sent_context) == sent


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
