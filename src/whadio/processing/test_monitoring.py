from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..meetings.monitoring import MeetingMetadata
from ..shared.pagination import ListWindow
from .enums import JobStatus, JobType
from .models import ProcessingJob
from .monitoring import JobFilter, JobMonitoring, safe_failure, snapshot
from .repositories import JobRepository

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def job_fixture(status: JobStatus) -> ProcessingJob:
    return ProcessingJob(
        processing_job_id=uuid4(),
        meeting_id=uuid4(),
        job_type=JobType.TRANSCRIPTION,
        status=status,
        attempts=2,
        created_at=NOW - timedelta(seconds=120),
        queued_at=NOW - timedelta(seconds=30),
        started_at=NOW - timedelta(seconds=10) if status != JobStatus.QUEUED else None,
        finished_at=NOW if status in (JobStatus.FAILED, JobStatus.SUCCEEDED) else None,
    )


@pytest.mark.parametrize(
    ("status", "wait", "running", "duration"),
    [
        (JobStatus.QUEUED, 30, None, None),
        (JobStatus.RUNNING, None, 10, None),
        (JobStatus.FAILED, None, None, 10),
        (JobStatus.SUCCEEDED, None, None, 10),
    ],
)
def test_job_durations_are_specific_to_current_state(
    status: JobStatus, wait: float | None, running: float | None, duration: float | None
) -> None:
    # Arrange
    job = job_fixture(status)
    # Act
    found = snapshot(job, uuid4(), NOW)
    # Assert
    assert (
        found.queue_wait_seconds,
        found.running_seconds,
        found.last_attempt_duration_seconds,
        found.total_elapsed_seconds,
    ) == (wait, running, duration, 120)


def test_unknown_historical_queue_time_stays_unknown() -> None:
    # Arrange
    job = job_fixture(JobStatus.QUEUED)
    job.queued_at = None
    # Act
    found = snapshot(job, uuid4(), NOW)
    # Assert
    assert (found.queue_wait_seconds, found.running_seconds) == (None, None)


def test_clock_skew_is_flagged_without_negative_duration() -> None:
    # Arrange
    job = job_fixture(JobStatus.RUNNING)
    job.started_at = NOW + timedelta(seconds=2)
    # Act
    found = snapshot(job, uuid4(), NOW)
    # Assert
    assert (found.running_seconds, found.timing_anomaly) == (0, True)


@pytest.mark.parametrize(
    "reason",
    [
        "transcript secret",
        "https://storage.example/key?signature=secret",
        "provider echoed a secret",
        "<script>bad</script>",
    ],
)
def test_unknown_failure_strings_never_reach_monitoring(reason: str) -> None:
    # Arrange
    job = job_fixture(JobStatus.FAILED)
    job.failure_reason = reason
    # Act
    found = snapshot(job, uuid4(), NOW)
    # Assert
    assert (found.failure_code, found.failure_description) == (
        "unknown_failure",
        "Unknown failure.",
    )


def test_known_failure_reason_remains_useful() -> None:
    # Arrange
    reason = "provider_rate_limited"
    # Act
    code = safe_failure(reason)
    # Assert
    assert code == reason


@pytest.mark.slow
def test_requeue_resets_only_current_attempt_timing(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[JobStatus, bool, bool, int]:
        meeting = await AsyncDatabase.add_meeting(
            session, await AsyncDatabase.add_workspace(session)
        )
        repository = JobRepository(session)
        job_id = await repository.add(meeting, JobType.NOTES)
        await repository.mark_running(job_id, NOW)
        # Act
        await repository.requeue(job_id)
        await session.flush()
        job = await session.get(ProcessingJob, job_id, populate_existing=True)
        if job is None:
            raise AssertionError("Job disappeared")
        return job.status, job.started_at is None, job.queued_at is not None, job.attempts

    found = async_database.run(scenario)
    # Assert
    assert found == (JobStatus.QUEUED, True, True, 1)


@pytest.mark.slow
def test_operational_queries_resolve_workspace_without_content(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        place = await AsyncDatabase.add_workspace(session)
        meeting = await AsyncDatabase.add_meeting(session, place)
        job_id = await JobRepository(session).add(meeting, JobType.NOTES)
        metadata = MeetingMetadata(session)
        workspace = (await metadata.workspaces([meeting]))[meeting]
        # Act
        found = await JobMonitoring(session, metadata).jobs(
            JobFilter(workspace_id=workspace), ListWindow(100), NOW
        )
        return len(found), found[0].job_id == job_id

    found = async_database.run(scenario)
    # Assert
    assert found == (1, True)


def test_terminal_job_without_a_start_flags_clock_skew_in_total_age() -> None:
    # Arrange
    job = job_fixture(JobStatus.FAILED)
    job.created_at = NOW + timedelta(seconds=1)
    job.started_at = None
    # Act
    found = snapshot(job, uuid4(), NOW)
    # Assert
    assert (found.total_elapsed_seconds, found.timing_anomaly) == (0, True)
