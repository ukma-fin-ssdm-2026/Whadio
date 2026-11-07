import asyncio
from datetime import UTC, datetime, timedelta

from .recovery import BATCH_SIZE, JobRecovery
from .settings import JobRecoverySettings

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


class StalledJobs:
    def __init__(self, returned: int = 0) -> None:
        self.returned: int = returned
        self.asked: list[tuple[datetime, int]] = []

    async def return_unstarted(self, published_before: datetime, limit: int) -> int:
        self.asked.append((published_before, limit))
        return self.returned


def recover(jobs: StalledJobs) -> int:
    return asyncio.run(
        JobRecovery(jobs, JobRecoverySettings(unstarted_limit=timedelta(hours=6))).recover(NOW)
    )


def test_recovery_asks_for_jobs_published_before_now_minus_the_limit() -> None:
    # Arrange
    jobs = StalledJobs()
    # Act
    recover(jobs)
    # Assert
    assert jobs.asked == [(NOW - timedelta(hours=6), BATCH_SIZE)]


def test_recovery_reports_how_many_jobs_it_returned() -> None:
    # Arrange
    jobs = StalledJobs(returned=3)
    # Act
    returned = recover(jobs)
    # Assert
    assert returned == 3
