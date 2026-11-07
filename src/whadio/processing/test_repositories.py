from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..meetings.contracts import ContextReference
from .enums import JobStatus, JobType
from .models import ProcessingJob
from .recovery import BATCH_SIZE
from .repositories import Job, JobRepository

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


async def add_job(
    session: AsyncSession, job_type: JobType = JobType.TRANSCRIPTION
) -> tuple[JobRepository, UUID, UUID]:
    meeting_id = await AsyncDatabase.add_meeting(
        session, await AsyncDatabase.add_workspace(session)
    )
    jobs = JobRepository(session)
    return jobs, meeting_id, await jobs.add(meeting_id, job_type)


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


# --- Job recovery ---

LONG_AGO = datetime(1990, 3, 1, tzinfo=UTC)
TICK = timedelta(microseconds=1)


async def stored_job(
    session: AsyncSession,
    status: JobStatus,
    published_at: datetime | None = LONG_AGO,
    job_type: JobType = JobType.TRANSCRIPTION,
) -> tuple[JobRepository, UUID]:
    """A job of a new meeting, brought into `status` long ago."""
    jobs, _, job_id = await add_job(session, job_type)
    if published_at is not None:
        await jobs.mark_published(job_id, published_at, ())
    if status is not JobStatus.QUEUED:
        await jobs.mark_running(job_id, LONG_AGO)
    if status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        await jobs.finish(job_id, status, LONG_AGO, None)
    return jobs, job_id


async def stored(session: AsyncSession, job_id: UUID) -> ProcessingJob:
    return await session.get_one(ProcessingJob, job_id, populate_existing=True)


type JobState = tuple[JobStatus, int, datetime | None, datetime | None]


async def state(session: AsyncSession, job_id: UUID) -> JobState:
    job = await stored(session, job_id)
    return job.status, job.attempts, job.published_at, job.started_at


@pytest.mark.slow
@pytest.mark.parametrize(
    ("published_before", "published_at"),
    [
        pytest.param(LONG_AGO - TICK, LONG_AGO, id="bva-below-limit"),
        pytest.param(LONG_AGO, LONG_AGO, id="bva-on-limit"),
        pytest.param(LONG_AGO + TICK, None, id="bva-above-limit"),
    ],
)
def test_published_job_is_returned_only_once_past_the_unstarted_limit(
    async_database: AsyncDatabase, published_before: datetime, published_at: datetime | None
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> datetime | None:
        jobs, job_id = await stored_job(session, JobStatus.QUEUED)
        # Act
        await jobs.return_unstarted(published_before, BATCH_SIZE)
        return (await stored(session, job_id)).published_at

    found = async_database.run(scenario)
    # Assert
    assert found == published_at


@pytest.mark.slow
def test_returned_job_gains_an_attempt(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[JobStatus, int]:
        jobs, job_id = await stored_job(session, JobStatus.QUEUED)
        # Act
        await jobs.return_unstarted(LONG_AGO + TICK, BATCH_SIZE)
        job = await stored(session, job_id)
        return job.status, job.attempts

    found = async_database.run(scenario)
    # Assert
    assert found == (JobStatus.QUEUED, 1)


@pytest.mark.slow
def test_returned_job_is_the_next_unpublished_one(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID | None, UUID]:
        await only_new_jobs_unpublished(session)
        jobs, job_id = await stored_job(session, JobStatus.QUEUED)
        # Act
        await jobs.return_unstarted(LONG_AGO + TICK, BATCH_SIZE)
        found = await jobs.next_unpublished()
        return None if found is None else found.job_id, job_id

    found, job_id = async_database.run(scenario)
    # Assert
    assert found == job_id


@pytest.mark.slow
@pytest.mark.parametrize(
    ("status", "published_at"),
    [
        pytest.param(JobStatus.QUEUED, None, id="queued-unpublished"),
        pytest.param(JobStatus.RUNNING, LONG_AGO, id="running"),
        pytest.param(JobStatus.SUCCEEDED, LONG_AGO, id="succeeded"),
        pytest.param(JobStatus.FAILED, LONG_AGO, id="failed"),
    ],
)
def test_job_that_is_not_waiting_for_a_worker_is_left_past_the_unstarted_limit(
    async_database: AsyncDatabase, status: JobStatus, published_at: datetime | None
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[JobState, JobState]:
        jobs, job_id = await stored_job(session, status, published_at)
        before = await state(session, job_id)
        # Act
        await jobs.return_unstarted(LONG_AGO + timedelta(days=1), BATCH_SIZE)
        return before, await state(session, job_id)

    before, after = async_database.run(scenario)
    # Assert
    assert after == before


@pytest.mark.slow
def test_recovery_returns_at_most_its_batch_oldest_first(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[bool]:
        jobs, older = await stored_job(session, JobStatus.QUEUED)
        _, newer = await stored_job(session, JobStatus.QUEUED, LONG_AGO + TICK)
        # Act
        await jobs.return_unstarted(LONG_AGO + timedelta(days=1), 1)
        return [(await stored(session, job_id)).published_at is None for job_id in (older, newer)]

    found = async_database.run(scenario)
    # Assert
    assert found == [True, False]


@pytest.mark.slow
@pytest.mark.parametrize("job_type", [JobType.TRANSCRIPTION, JobType.NOTES])
@pytest.mark.parametrize(
    ("started_before", "expected"),
    [
        pytest.param(LONG_AGO - TICK, (JobStatus.RUNNING, 1, LONG_AGO), id="bva-below-limit"),
        pytest.param(LONG_AGO, (JobStatus.RUNNING, 1, LONG_AGO), id="bva-on-limit"),
        pytest.param(LONG_AGO + TICK, (JobStatus.QUEUED, 1, None), id="bva-above-limit"),
    ],
)
def test_running_job_is_returned_with_its_attempts_only_once_past_its_running_limit(
    async_database: AsyncDatabase,
    job_type: JobType,
    started_before: datetime,
    expected: tuple[JobStatus, int, datetime | None],
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[JobStatus, int, datetime | None]:
        jobs, job_id = await stored_job(session, JobStatus.RUNNING, job_type=job_type)
        # Act
        await jobs.return_running({job_type: started_before}, BATCH_SIZE)
        status, attempts, _, started_at = await state(session, job_id)
        return status, attempts, started_at

    found = async_database.run(scenario)
    # Assert
    assert found == expected


@pytest.mark.slow
def test_running_job_is_judged_by_the_limit_of_its_own_type(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> JobStatus:
        jobs, job_id = await stored_job(session, JobStatus.RUNNING, job_type=JobType.NOTES)
        # Act
        await jobs.return_running(
            {JobType.TRANSCRIPTION: LONG_AGO + TICK, JobType.NOTES: LONG_AGO}, BATCH_SIZE
        )
        return (await stored(session, job_id)).status

    found = async_database.run(scenario)
    # Assert
    assert found is JobStatus.RUNNING
