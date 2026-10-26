import hashlib
from datetime import UTC, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime, Field, model_validator

from ...admin.services import MetricsSnapshot
from ...processing.enums import JobStatus, JobType
from ...processing.monitoring import JobFilter, JobSnapshot
from ...shared.pagination import ListCursor
from ..accounts.auth import BrowserUser
from ..composition import Administration, Administrators, MonitoredJobs
from ..core.errors import error_responses
from ..core.pagination import list_page, list_window
from ..core.schemas import Output, Page, PageQuery


async def require_administrator(user: BrowserUser, service: Administrators) -> None:
    await service.require(user.id)


router = APIRouter(
    tags=["admin"],
    dependencies=[Depends(require_administrator)],
    responses=error_responses(
        {
            401: "Browser session required",
            403: "INSUFFICIENT_ROLE: administrator permission required",
            422: "Invalid filter or cursor",
        }
    ),
)


class JobQuery(PageQuery):
    workspace_id: UUID | None = Field(default=None, description="Filter by workspace ID")
    job_type: JobType | None = Field(default=None, description="Filter by transcription or notes")
    status: JobStatus | None = Field(default=None, description="Filter by logical-job state")
    created_from: AwareDatetime | None = Field(
        default=None, description="Inclusive original enqueue-time lower bound"
    )
    created_to: AwareDatetime | None = Field(
        default=None, description="Inclusive original enqueue-time upper bound"
    )

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise ValueError("Creation interval must be chronological")
        return self


class MetricsRead(MetricsSnapshot, Output):
    pass


@router.get(
    "/admin/jobs",
    summary="List operational jobs",
    description=(
        "Administrator-only metadata, newest enqueue time then job ID "
        "descending. One as_of timestamp per page. Filters are bound into the "
        "cursor. Counts and jobs disappear with their meetings; no content, "
        "names or raw failures are exposed."
    ),
)
async def jobs(
    query: Annotated[JobQuery, Query()],
    service: MonitoredJobs,
    response: Response,
) -> Page[JobSnapshot]:
    scope = (
        "admin-jobs:"
        + hashlib.sha256(query.model_dump_json(exclude={"cursor", "limit"}).encode()).hexdigest()
    )
    filters = JobFilter(
        query.workspace_id, query.job_type, query.status, query.created_from, query.created_to
    )
    items = await service.jobs(
        filters, list_window(query, scope, chronological=True), datetime.now(UTC)
    )

    last = items[min(len(items), query.limit) - 1] if items else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.job_id)
    response.headers["Cache-Control"] = "no-store"
    return list_page(items, query, scope, cursor)


@router.get(
    "/admin/metrics",
    summary="Read operational metrics",
    description=(
        "Administrator-only logical-job aggregates read from PostgreSQL. "
        "Unknown queue waiting times remain null. No host or model telemetry "
        "is required or returned."
    ),
)
async def metrics(service: Administration, response: Response) -> MetricsRead:
    result = await service.metrics(datetime.now(UTC))

    response.headers["Cache-Control"] = "no-store"
    return MetricsRead.model_validate(result.model_dump())
