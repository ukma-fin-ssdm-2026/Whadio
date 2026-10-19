from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from ..contracts.notes import NotesFailure
from ..contracts.transcription import TranscriptionFailure
from ..meetings.monitoring import IMeetingMetadata
from ..shared.pagination import ListWindow
from .enums import JobStatus, JobType
from .models import ProcessingJob


@dataclass(frozen=True)
class JobFilter:
    workspace_id: UUID | None = None
    job_type: JobType | None = None
    status: JobStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


class JobSnapshot(BaseModel):
    job_id: UUID = Field(description="Logical job identifier; grants no content access")
    workspace_id: UUID = Field(
        description="Workspace identifier without its potentially sensitive name"
    )
    job_type: JobType = Field(description="Transcription or notes")
    status: JobStatus = Field(description="Persisted logical-job state")
    created_at: datetime = Field(description="Original enqueue time in UTC")
    queued_at: datetime | None = Field(
        description="Entry into current queued period; null for unknown historical retries"
    )
    started_at: datetime | None = Field(
        description="Current or final attempt start, null before start"
    )
    finished_at: datetime | None = Field(description="Final completion time, null until terminal")
    attempts_started: int = Field(
        description="Number of accepted attempt starts, including the first"
    )
    as_of: datetime = Field(description="Common observation time used for duration calculations")
    queue_wait_seconds: float | None = Field(
        description="Current queue wait; null outside queued state or if unknown"
    )
    running_seconds: float | None = Field(
        description="Current attempt running time; null outside running state"
    )
    last_queue_wait_seconds: float | None = Field(
        description="Wait preceding the started attempt, when known"
    )
    last_attempt_duration_seconds: float | None = Field(
        description="Final attempt duration for a terminal started job"
    )
    total_elapsed_seconds: float = Field(
        description="Logical-job age including all waits/retries, frozen at completion"
    )
    failure_code: str | None = Field(
        description="Allowlisted failure code; no raw exception or provider text"
    )
    failure_description: str | None = Field(description="Fixed safe explanation of the failure")
    timing_anomaly: bool = Field(description="A clock-skew duration was bounded at zero")


class JobCounts(BaseModel):
    job_type: JobType = Field(description="Job type")
    queued: int = Field(description="Distinct retained queued jobs")
    running: int = Field(description="Distinct retained running jobs")
    failed: int = Field(description="Distinct retained failed jobs, not lifetime failures")
    unpublished: int = Field(description="Queued jobs not yet published")
    oldest_queue_wait_seconds: float | None = Field(
        description="Oldest known current queue wait; null when none is known"
    )
    unknown_queue_waits: int = Field(
        description="Queued historical jobs whose current queue-entry time is unknown"
    )


def safe_failure(reason: str | None) -> str | None:
    if reason is None:
        return None
    allowed = {item.value for item in NotesFailure} | {item.value for item in TranscriptionFailure}
    allowed.update(("dead_lettered", "transcript_exists", "unpublishable"))
    return reason if reason in allowed else "unknown_failure"


def snapshot(job: ProcessingJob, workspace: UUID, now: datetime) -> JobSnapshot:
    terminal = job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
    durations: list[float] = []

    def elapsed(end: datetime | None, start: datetime | None) -> float | None:
        if start is None or end is None:
            return None
        value = (end - start).total_seconds()
        durations.append(value)
        return max(0.0, value)

    queue = elapsed(now, job.queued_at) if job.status == JobStatus.QUEUED else None
    running = elapsed(now, job.started_at) if job.status == JobStatus.RUNNING else None
    wait = elapsed(job.started_at, job.queued_at) if job.status != JobStatus.QUEUED else None
    duration = elapsed(job.finished_at, job.started_at) if terminal else None
    raw_age = (
        (job.finished_at if terminal and job.finished_at is not None else now) - job.created_at
    ).total_seconds()
    durations.append(raw_age)
    age = max(0.0, raw_age)
    code = safe_failure(job.failure_reason) if job.status == JobStatus.FAILED else None
    if job.status == JobStatus.FAILED and code is None:
        code = "unknown_failure"
    return JobSnapshot(
        job_id=job.processing_job_id,
        workspace_id=workspace,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        attempts_started=job.attempts,
        as_of=now,
        queue_wait_seconds=queue,
        running_seconds=running,
        last_queue_wait_seconds=wait,
        last_attempt_duration_seconds=duration,
        total_elapsed_seconds=age,
        failure_code=code,
        failure_description=None if code is None else code.replace("_", " ").capitalize() + ".",
        timing_anomaly=any(value < 0 for value in durations),
    )


class IJobMonitoring(Protocol):
    async def jobs(
        self, filters: JobFilter, page: ListWindow, now: datetime
    ) -> list[JobSnapshot]: ...

    async def counts(self, now: datetime) -> list[JobCounts]: ...


class JobMonitoring:
    def __init__(self, session: AsyncSession, meetings: IMeetingMetadata) -> None:
        self._session: AsyncSession = session
        self._meetings: IMeetingMetadata = meetings

    async def jobs(self, filters: JobFilter, page: ListWindow, now: datetime) -> list[JobSnapshot]:
        statement = select(ProcessingJob).options(
            load_only(
                ProcessingJob.processing_job_id,
                ProcessingJob.meeting_id,
                ProcessingJob.job_type,
                ProcessingJob.status,
                ProcessingJob.created_at,
                ProcessingJob.queued_at,
                ProcessingJob.started_at,
                ProcessingJob.finished_at,
                ProcessingJob.attempts,
                ProcessingJob.failure_reason,
            )
        )
        if filters.workspace_id is not None:
            statement = statement.where(
                ProcessingJob.meeting_id.in_(self._meetings.in_workspace(filters.workspace_id))
            )
        if filters.job_type is not None:
            statement = statement.where(ProcessingJob.job_type == filters.job_type)
        if filters.status is not None:
            statement = statement.where(ProcessingJob.status == filters.status)
        if filters.created_from is not None:
            statement = statement.where(ProcessingJob.created_at >= filters.created_from)
        if filters.created_to is not None:
            statement = statement.where(ProcessingJob.created_at <= filters.created_to)
        if page.after is not None:
            stamp = datetime.fromisoformat(page.after.key)
            statement = statement.where(
                (ProcessingJob.created_at < stamp)
                | (
                    (ProcessingJob.created_at == stamp)
                    & (ProcessingJob.processing_job_id < page.after.item_id)
                )
            )
        jobs = list(
            await self._session.scalars(
                statement.order_by(
                    ProcessingJob.created_at.desc(), ProcessingJob.processing_job_id.desc()
                ).limit(page.limit)
            )
        )
        workspaces = await self._meetings.workspaces([job.meeting_id for job in jobs])
        return [
            snapshot(job, workspaces[job.meeting_id], now)
            for job in jobs
            if job.meeting_id in workspaces
        ]

    async def counts(self, now: datetime) -> list[JobCounts]:
        rows = await self._session.execute(
            select(
                ProcessingJob.job_type,
                func.count().filter(ProcessingJob.status == JobStatus.QUEUED),
                func.count().filter(ProcessingJob.status == JobStatus.RUNNING),
                func.count().filter(ProcessingJob.status == JobStatus.FAILED),
                func.count().filter(
                    (ProcessingJob.status == JobStatus.QUEUED)
                    & ProcessingJob.published_at.is_(None)
                ),
                func.min(ProcessingJob.queued_at).filter(ProcessingJob.status == JobStatus.QUEUED),
                func.count().filter(
                    (ProcessingJob.status == JobStatus.QUEUED) & ProcessingJob.queued_at.is_(None)
                ),
            ).group_by(ProcessingJob.job_type)
        )
        return [
            JobCounts(
                job_type=kind,
                queued=queued,
                running=running,
                failed=failed,
                unpublished=unpublished,
                oldest_queue_wait_seconds=None
                if oldest is None
                else max(0, (now - oldest).total_seconds()),
                unknown_queue_waits=unknown,
            )
            for kind, queued, running, failed, unpublished, oldest, unknown in rows
        ]
