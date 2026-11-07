import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from .enums import JobType
from .recovery import BATCH_SIZE, JobRecovery
from .settings import JobRecoverySettings

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
LIMITS = JobRecoverySettings(
    unstarted_limit=timedelta(hours=6),
    transcription_running_limit=timedelta(hours=3),
    notes_running_limit=timedelta(hours=2),
)


class StalledJobs:
    def __init__(self, returned: int = 0) -> None:
        self.returned: int = returned
        self.unstarted: list[tuple[datetime, int]] = []
        self.running: list[tuple[dict[JobType, datetime], int]] = []

    async def return_unstarted(self, published_before: datetime, limit: int) -> int:
        self.unstarted.append((published_before, limit))
        return self.returned

    async def return_running(self, started_before: Mapping[JobType, datetime], limit: int) -> int:
        self.running.append((dict(started_before), limit))
        return self.returned


def recover(jobs: StalledJobs) -> int:
    return asyncio.run(JobRecovery(jobs, LIMITS).recover(NOW))


def test_recovery_asks_for_jobs_published_before_now_minus_the_limit() -> None:
    # Arrange
    jobs = StalledJobs()
    # Act
    recover(jobs)
    # Assert
    assert jobs.unstarted == [(NOW - timedelta(hours=6), BATCH_SIZE)]


def test_recovery_asks_for_jobs_started_before_now_minus_their_types_limit() -> None:
    # Arrange
    jobs = StalledJobs()
    # Act
    recover(jobs)
    # Assert
    assert jobs.running == [
        (
            {
                JobType.TRANSCRIPTION: NOW - timedelta(hours=3),
                JobType.NOTES: NOW - timedelta(hours=2),
            },
            BATCH_SIZE,
        )
    ]


def test_recovery_reports_how_many_jobs_it_returned_of_both_kinds() -> None:
    # Arrange
    jobs = StalledJobs(returned=3)
    # Act
    returned = recover(jobs)
    # Assert
    assert returned == 6
