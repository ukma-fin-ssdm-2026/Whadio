import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import OperationalError

from ..notifications.services import DrainResult
from ..retention.services import RetentionResult
from .services import RetentionScheduler


class RetentionJobs:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_cleanup: bool = False
        self.stop: asyncio.Event | None = None

    async def remove_deleted_meeting_recordings(self) -> list[UUID]:
        self.calls.append("cleanup")
        if self.fail_cleanup:
            raise OperationalError("database unavailable", None, RuntimeError())
        return []

    async def run(self, now: datetime) -> RetentionResult:
        del now
        self.calls.append("retention")
        if self.stop is not None:
            self.stop.set()
        return RetentionResult([], [], [uuid4()])


NOTHING_DUE = DrainResult(sent=0, failed=0)


class NotificationJobs:
    def __init__(self, calls: list[str], result: DrainResult = NOTHING_DUE) -> None:
        self.calls: list[str] = calls
        self.result: DrainResult = result
        self.fail_drain: bool = False

    async def drain(self) -> DrainResult:
        self.calls.append("drain")
        if self.fail_drain:
            raise OperationalError("database unavailable", None, RuntimeError())
        return self.result

    async def remove_finished(self) -> int:
        self.calls.append("remove sent")
        return 0


class RegistrationJobs:
    def __init__(self, calls: list[str], *, fail: bool = False) -> None:
        self.calls: list[str] = calls
        self.fail: bool = fail
        self.expired_at: datetime | None = None

    async def remove_expired(self, now: datetime) -> int:
        self.calls.append("registrations")
        self.expired_at = now
        if self.fail:
            raise OperationalError("database unavailable", None, RuntimeError())
        return 2


def test_tick_cleans_registrations_using_the_scheduler_clock() -> None:
    # Arrange
    now = datetime(2026, 10, 29, tzinfo=UTC)
    jobs = RetentionJobs()
    registrations = RegistrationJobs(jobs.calls)
    scheduler = RetentionScheduler(jobs, 60, lambda: now, registrations=registrations)
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert (registrations.expired_at, jobs.calls) == (
        now,
        ["registrations", "cleanup", "retention"],
    )


def test_registration_cleanup_failure_does_not_stop_other_scheduler_jobs() -> None:
    # Arrange
    jobs = RetentionJobs()
    scheduler = RetentionScheduler(
        jobs,
        60,
        notifications=NotificationJobs(jobs.calls),
        registrations=RegistrationJobs(jobs.calls, fail=True),
    )
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert (failures, jobs.calls) == (
        2,
        ["registrations", "cleanup", "retention", "drain", "remove sent"],
    )


def test_tick_delivers_notifications_after_retention() -> None:
    # Arrange
    jobs = RetentionJobs()
    scheduler = RetentionScheduler(jobs, 60, notifications=NotificationJobs(jobs.calls))
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert jobs.calls == ["cleanup", "retention", "drain", "remove sent"]


def test_failed_deliveries_count_as_failures_of_the_tick() -> None:
    # Arrange
    jobs = RetentionJobs()
    notifications = NotificationJobs(jobs.calls, DrainResult(sent=3, failed=2))
    scheduler = RetentionScheduler(jobs, 60, notifications=notifications)
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert failures == 3


def test_sent_notices_are_removed_when_delivery_database_access_fails() -> None:
    # Arrange
    jobs = RetentionJobs()
    notifications = NotificationJobs(jobs.calls)
    notifications.fail_drain = True
    scheduler = RetentionScheduler(jobs, 60, notifications=notifications)
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert (jobs.calls[-2:], failures) == (["drain", "remove sent"], 2)


def test_retention_still_runs_when_cleanup_database_access_fails() -> None:
    # Arrange
    jobs = RetentionJobs()
    jobs.fail_cleanup = True
    scheduler = RetentionScheduler(jobs, 60)
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert (jobs.calls, failures) == (["cleanup", "retention"], 2)


def test_shutdown_interrupts_interval_wait() -> None:
    # Arrange
    async def scenario() -> list[str]:
        jobs = RetentionJobs()
        jobs.stop = asyncio.Event()
        scheduler = RetentionScheduler(jobs, 3600, lambda: datetime(2026, 1, 1, tzinfo=UTC))
        # Act
        await asyncio.wait_for(scheduler.serve(jobs.stop), timeout=1)
        return jobs.calls

    # Assert
    assert asyncio.run(scenario()) == ["cleanup", "retention"]


def test_already_stopped_scheduler_runs_no_jobs() -> None:
    # Arrange
    async def scenario() -> list[str]:
        jobs = RetentionJobs()
        stop = asyncio.Event()
        stop.set()
        # Act
        await RetentionScheduler(jobs, 60).serve(stop)
        return jobs.calls

    # Assert
    assert asyncio.run(scenario()) == []
