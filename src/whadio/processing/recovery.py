from collections.abc import Mapping
from datetime import datetime
from typing import Final, Protocol

from .enums import JobType
from .settings import JobRecoverySettings

BATCH_SIZE: Final = 50


class IStalledJobs(Protocol):
    async def return_unstarted(self, published_before: datetime, limit: int, /) -> int:
        """Hand the oldest queued jobs published before then back to the publisher, each with one
        more attempt; how many were returned."""
        ...

    async def return_running(
        self, started_before: Mapping[JobType, datetime], limit: int, /
    ) -> int:
        """Hand the oldest running jobs started before their type's time back to the publisher,
        their attempts unchanged; how many were returned."""
        ...


class JobRecovery:
    """Never fails a job: the publisher fails one that comes back with its attempts used."""

    def __init__(self, jobs: IStalledJobs, limits: JobRecoverySettings) -> None:
        self._jobs: IStalledJobs = jobs
        self._limits: JobRecoverySettings = limits

    async def recover(self, now: datetime) -> int:
        limits = self._limits
        unstarted = await self._jobs.return_unstarted(now - limits.unstarted_limit, BATCH_SIZE)
        running = await self._jobs.return_running(
            {
                JobType.TRANSCRIPTION: now - limits.transcription_running_limit,
                JobType.NOTES: now - limits.notes_running_limit,
            },
            BATCH_SIZE,
        )
        return unstarted + running
