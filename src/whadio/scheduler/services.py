import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ..retention.services import RetentionResult

logger = logging.getLogger(__name__)


class IRetentionJobs(Protocol):
    async def run(self, now: datetime) -> RetentionResult: ...

    async def remove_deleted_meeting_recordings(self) -> list[UUID]: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class RetentionScheduler:
    def __init__(
        self,
        retention: IRetentionJobs,
        interval_seconds: float,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("The retention interval must be positive")
        self._retention: IRetentionJobs = retention
        self._interval_seconds: float = interval_seconds
        self._now: Callable[[], datetime] = now

    async def tick(self) -> int:
        failed = 0
        try:
            failed += len(await self._retention.remove_deleted_meeting_recordings())
        except SQLAlchemyError:
            failed += 1
            logger.warning("Recording cleanup could not access the database")
        try:
            result = await self._retention.run(self._now())
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
        return failed

    async def serve(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue
