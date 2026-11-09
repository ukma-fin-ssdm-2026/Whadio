import asyncio
import logging
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from ..notifications.services import DrainResult
from ..retention.services import RetentionResult
from .services import PeriodicJobs, RetentionScheduler


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


REGISTRATION_STEPS = ("registrations", "password resets", "sessions")


class RegistrationJobs:
    def __init__(
        self, calls: list[str], *, failing: Collection[str] = (), removed: int = 2
    ) -> None:
        self.calls: list[str] = calls
        self.failing: Collection[str] = failing
        self.removed: int = removed
        self.expired_at: dict[str, datetime] = {}

    def _remove(self, step: str, now: datetime) -> int:
        self.calls.append(step)
        self.expired_at[step] = now
        if step in self.failing:
            raise OperationalError("database unavailable", None, RuntimeError())
        return self.removed

    async def remove_expired(self, now: datetime) -> int:
        return self._remove("registrations", now)

    async def remove_expired_password_resets(self, now: datetime) -> int:
        return self._remove("password resets", now)

    async def remove_expired_sessions(self, now: datetime) -> int:
        return self._remove("sessions", now)


def test_tick_cleans_registrations_using_the_scheduler_clock() -> None:
    # Arrange
    now = datetime(2026, 10, 29, tzinfo=UTC)
    jobs = RetentionJobs()
    registrations = RegistrationJobs(jobs.calls)
    scheduler = RetentionScheduler(jobs, 60, lambda: now, PeriodicJobs(registrations=registrations))
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert (registrations.expired_at.get("registrations"), jobs.calls) == (
        now,
        [*REGISTRATION_STEPS, "cleanup", "retention"],
    )


def test_tick_deletes_expired_sessions_using_the_scheduler_clock() -> None:
    # Arrange
    now = datetime(2026, 11, 7, tzinfo=UTC)
    registrations = RegistrationJobs([])
    scheduler = RetentionScheduler(
        RetentionJobs(), 60, lambda: now, PeriodicJobs(registrations=registrations)
    )
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert registrations.expired_at.get("sessions") == now


def test_session_cleanup_logs_how_many_sessions_it_deleted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    caplog.set_level(logging.INFO, logger="whadio.scheduler.services")
    periodic = PeriodicJobs(registrations=RegistrationJobs([], removed=3))
    scheduler = RetentionScheduler(RetentionJobs(), 60, periodic=periodic)
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert "Session cleanup: 3 expired sessions deleted" in caplog.messages


def ticked_with_failing_registrations(failing: Collection[str]) -> tuple[int, list[str]]:
    """The tick's failure count and the jobs it ran, notification delivery included."""
    jobs = RetentionJobs()
    periodic = PeriodicJobs(
        notifications=NotificationJobs(jobs.calls),
        registrations=RegistrationJobs(jobs.calls, failing=failing),
    )
    return asyncio.run(RetentionScheduler(jobs, 60, periodic=periodic).tick()), jobs.calls


def test_registration_cleanup_failure_does_not_stop_other_scheduler_jobs() -> None:
    # Act
    ticked = ticked_with_failing_registrations(REGISTRATION_STEPS)
    # Assert
    assert ticked == (4, [*REGISTRATION_STEPS, "cleanup", "retention", "drain", "remove sent"])


def test_session_cleanup_failure_is_counted_and_the_other_jobs_still_run() -> None:
    # Act
    ticked = ticked_with_failing_registrations({"sessions"})
    # Assert
    assert ticked == (2, [*REGISTRATION_STEPS, "cleanup", "retention", "drain", "remove sent"])


def test_tick_delivers_notifications_after_retention() -> None:
    # Arrange
    jobs = RetentionJobs()
    scheduler = RetentionScheduler(
        jobs, 60, periodic=PeriodicJobs(notifications=NotificationJobs(jobs.calls))
    )
    # Act
    asyncio.run(scheduler.tick())
    # Assert
    assert jobs.calls == ["cleanup", "retention", "drain", "remove sent"]


def test_failed_deliveries_count_as_failures_of_the_tick() -> None:
    # Arrange
    jobs = RetentionJobs()
    notifications = NotificationJobs(jobs.calls, DrainResult(sent=3, failed=2))
    scheduler = RetentionScheduler(jobs, 60, periodic=PeriodicJobs(notifications=notifications))
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert failures == 3


def test_sent_notices_are_removed_when_delivery_database_access_fails() -> None:
    # Arrange
    jobs = RetentionJobs()
    notifications = NotificationJobs(jobs.calls)
    notifications.fail_drain = True
    scheduler = RetentionScheduler(jobs, 60, periodic=PeriodicJobs(notifications=notifications))
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


NOW = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)


class JobRecovery:
    def __init__(self, calls: list[str], *, fail: bool = False) -> None:
        self.calls: list[str] = calls
        self.fail: bool = fail
        self.recovered_at: datetime | None = None

    async def recover(self, now: datetime) -> int:
        self.calls.append("job recovery")
        self.recovered_at = now
        if self.fail:
            raise OperationalError("database unavailable", None, RuntimeError())
        return 1


def scheduler_with_recovery(jobs: RetentionJobs, recovery: JobRecovery) -> RetentionScheduler:
    periodic = PeriodicJobs(notifications=NotificationJobs(jobs.calls), job_recovery=recovery)
    return RetentionScheduler(jobs, 60, lambda: NOW, periodic)


def test_tick_recovers_jobs_by_the_scheduler_clock_after_retention_and_before_delivery() -> None:
    # Arrange
    jobs = RetentionJobs()
    recovery = JobRecovery(jobs.calls)
    # Act
    asyncio.run(scheduler_with_recovery(jobs, recovery).tick())
    # Assert
    assert (recovery.recovered_at, jobs.calls) == (
        NOW,
        ["cleanup", "retention", "job recovery", "drain", "remove sent"],
    )


def test_job_recovery_failure_is_counted_and_the_other_jobs_still_run() -> None:
    # Arrange
    jobs = RetentionJobs()
    scheduler = scheduler_with_recovery(jobs, JobRecovery(jobs.calls, fail=True))
    # Act
    failures = asyncio.run(scheduler.tick())
    # Assert
    assert (failures, jobs.calls) == (
        2,
        ["cleanup", "retention", "job recovery", "drain", "remove sent"],
    )
