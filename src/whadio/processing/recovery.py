from datetime import datetime
from typing import Final, Protocol

from .settings import JobRecoverySettings

BATCH_SIZE: Final = 50


class IStalledJobs(Protocol):
    async def return_unstarted(self, published_before: datetime, limit: int, /) -> int:
        """Hand the oldest queued jobs published before then back to the publisher, each with one
        more attempt; how many were returned."""
        ...


class JobRecovery:
    """Never fails a job: the publisher fails one that comes back with its attempts used."""

    def __init__(self, jobs: IStalledJobs, limits: JobRecoverySettings) -> None:
        self._jobs: IStalledJobs = jobs
        self._limits: JobRecoverySettings = limits

    async def recover(self, now: datetime) -> int:
        return await self._jobs.return_unstarted(now - self._limits.unstarted_limit, BATCH_SIZE)
