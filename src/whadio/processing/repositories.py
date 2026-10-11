from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import JobStatus, JobType
from .models import ProcessingJob


@dataclass(frozen=True, slots=True)
class Job:
    job_id: UUID
    meeting_id: UUID
    job_type: JobType
    status: JobStatus
    attempts: int


class IJobRepository(Protocol):
    async def add(self, meeting_id: UUID, job_type: JobType, /) -> UUID: ...

    async def lock(self, job_id: UUID, /) -> Job | None: ...

    async def mark_running(self, job_id: UUID, started_at: datetime, /) -> None: ...

    async def requeue(self, job_id: UUID, /) -> None: ...

    async def finish(
        self,
        job_id: UUID,
        status: JobStatus,
        finished_at: datetime,
        failure_reason: str | None,
        /,
    ) -> None: ...


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def add(self, meeting_id: UUID, job_type: JobType) -> UUID:
        job = ProcessingJob(meeting_id=meeting_id, job_type=job_type, status=JobStatus.QUEUED)
        self._session.add(job)
        await self._session.flush()
        return job.processing_job_id

    async def lock(self, job_id: UUID) -> Job | None:
        # Results of one job can arrive together (a redelivery next to the original); the lock
        # makes them take turns.
        found = await self._session.scalar(
            select(ProcessingJob).where(ProcessingJob.processing_job_id == job_id).with_for_update()
        )
        if found is None:
            return None
        return Job(
            job_id=found.processing_job_id,
            meeting_id=found.meeting_id,
            job_type=found.job_type,
            status=found.status,
            attempts=found.attempts,
        )

    async def mark_running(self, job_id: UUID, started_at: datetime) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.processing_job_id == job_id)
            .values(
                status=JobStatus.RUNNING,
                started_at=started_at,
                attempts=ProcessingJob.attempts + 1,
            )
        )

    async def requeue(self, job_id: UUID) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.processing_job_id == job_id)
            .values(status=JobStatus.QUEUED)
        )

    async def finish(
        self, job_id: UUID, status: JobStatus, finished_at: datetime, failure_reason: str | None
    ) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.processing_job_id == job_id)
            .values(status=status, finished_at=finished_at, failure_reason=failure_reason)
        )
