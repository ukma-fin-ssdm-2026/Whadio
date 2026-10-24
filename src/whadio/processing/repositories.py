from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..meetings.contracts import ContextReference
from .enums import JobStatus, JobType
from .models import ProcessingJob


@dataclass(frozen=True, slots=True)
class Job:
    job_id: UUID
    meeting_id: UUID
    job_type: JobType
    status: JobStatus
    attempts: int
    sent_context: tuple[ContextReference, ...] = ()


class IJobRepository(Protocol):
    async def add(self, meeting_id: UUID, job_type: JobType, /) -> UUID: ...

    async def lock(self, job_id: UUID, /) -> Job | None: ...

    async def next_unpublished(self) -> Job | None: ...

    async def has_unfinished(self, meeting_id: UUID, job_type: JobType, /) -> bool: ...

    async def mark_published(
        self, job_id: UUID, published_at: datetime, context: tuple[ContextReference, ...], /
    ) -> None: ...

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


class _SentMeeting(BaseModel):
    meeting_id: UUID = Field(description="Context meeting sent with the notes request")
    name: str = Field(description="Its name as sent")


_SENT_CONTEXT: Final = TypeAdapter(list[_SentMeeting])


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
        return None if found is None else _job(found)

    async def next_unpublished(self) -> Job | None:
        # Skipping locked rows lets several web instances publish side by side, each job once.
        found = await self._session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.status == JobStatus.QUEUED, ProcessingJob.published_at.is_(None))
            .order_by(ProcessingJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return None if found is None else _job(found)

    async def has_unfinished(self, meeting_id: UUID, job_type: JobType) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        ProcessingJob.meeting_id == meeting_id,
                        ProcessingJob.job_type == job_type,
                        ProcessingJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                    )
                )
            )
        )

    async def mark_published(
        self, job_id: UUID, published_at: datetime, context: tuple[ContextReference, ...]
    ) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.processing_job_id == job_id)
            .values(
                published_at=published_at,
                sent_context=_SENT_CONTEXT.dump_python(
                    [_SentMeeting(meeting_id=item.meeting_id, name=item.name) for item in context],
                    mode="json",
                ),
            )
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
            .values(
                status=JobStatus.QUEUED,
                published_at=None,
                queued_at=func.clock_timestamp(),
                started_at=None,
                finished_at=None,
            )
        )

    async def finish(
        self, job_id: UUID, status: JobStatus, finished_at: datetime, failure_reason: str | None
    ) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.processing_job_id == job_id)
            .values(status=status, finished_at=finished_at, failure_reason=failure_reason)
        )


def _job(found: ProcessingJob) -> Job:
    sent = [] if found.sent_context is None else _SENT_CONTEXT.validate_python(found.sent_context)
    return Job(
        job_id=found.processing_job_id,
        meeting_id=found.meeting_id,
        job_type=found.job_type,
        status=found.status,
        attempts=found.attempts,
        sent_context=tuple(ContextReference(item.meeting_id, item.name) for item in sent),
    )
