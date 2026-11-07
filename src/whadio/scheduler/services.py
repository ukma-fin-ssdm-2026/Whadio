import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ..notifications.services import DrainResult
from ..retention.services import RetentionResult

logger = logging.getLogger(__name__)


class IJobRecovery(Protocol):
    async def recover(self, now: datetime) -> int: ...


class IRetentionJobs(Protocol):
    async def run(self, now: datetime) -> RetentionResult: ...

    async def remove_deleted_meeting_recordings(self) -> list[UUID]: ...


class INotificationJobs(Protocol):
    async def drain(self) -> DrainResult: ...

    async def remove_finished(self) -> int: ...


class IRegistrationJobs(Protocol):
    async def remove_expired(self, now: datetime) -> int: ...

    async def remove_expired_password_resets(self, now: datetime) -> int: ...

    async def remove_expired_sessions(self, now: datetime) -> int: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PeriodicJobs:
    """The jobs each tick runs besides retention; one left out is skipped."""

    notifications: INotificationJobs | None = None
    registrations: IRegistrationJobs | None = None
    job_recovery: IJobRecovery | None = None


class RetentionScheduler:
    def __init__(
        self,
        retention: IRetentionJobs,
        interval_seconds: float,
        now: Callable[[], datetime] = utc_now,
        periodic: PeriodicJobs | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("The retention interval must be positive")
        self._retention: IRetentionJobs = retention
        self._interval_seconds: float = interval_seconds
        self._now: Callable[[], datetime] = now
        self._periodic: PeriodicJobs = periodic or PeriodicJobs()

    async def tick(self) -> int:
        failed = 0
        now = self._now()
        registrations = self._periodic.registrations
        if registrations is not None:
            try:
                removed = await registrations.remove_expired(now)
                logger.info("Account link cleanup: %d expired links deleted", removed)
            except SQLAlchemyError:
                failed += 1
                logger.warning("Account link cleanup could not access the database")
            try:
                removed = await registrations.remove_expired_password_resets(now)
                logger.info("Password-reset cleanup: %d expired links deleted", removed)
            except SQLAlchemyError:
                failed += 1
                logger.warning("Password-reset cleanup could not access the database")
            try:
                removed = await registrations.remove_expired_sessions(now)
                logger.info("Session cleanup: %d expired sessions deleted", removed)
            except SQLAlchemyError:
                failed += 1
                logger.warning("Session cleanup could not access the database")
        try:
            failed += len(await self._retention.remove_deleted_meeting_recordings())
        except SQLAlchemyError:
            failed += 1
            logger.warning("Recording cleanup could not access the database")
        try:
            result = await self._retention.run(now)
            failed += len(result.failed)
            logger.info(
                "Retention pass: %d warned, %d deleted, %d failed",
                len(result.warned),
                len(result.deleted),
                len(result.failed),
            )
        except SQLAlchemyError:
            failed += 1
            logger.warning("Retention could not access the database")
        if self._periodic.job_recovery is not None:
            try:
                returned = await self._periodic.job_recovery.recover(now)
                logger.info("Job recovery: %d jobs returned to the queue", returned)
            except SQLAlchemyError:
                failed += 1
                logger.warning("Job recovery could not access the database")
        if self._periodic.notifications is not None:
            failed += await self._deliver_notifications(self._periodic.notifications)
        return failed

    @staticmethod
    async def _deliver_notifications(notifications: INotificationJobs) -> int:
        failed = 0
        try:
            result = await notifications.drain()
            failed += result.failed
            logger.info("Notification pass: %d sent, %d failed", result.sent, result.failed)
        except SQLAlchemyError:
            failed += 1
            logger.warning("Notification delivery could not access the database")
        try:
            await notifications.remove_finished()
        except SQLAlchemyError:
            failed += 1
            logger.warning("Notification cleanup could not access the database")
        return failed

    async def serve(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue
