import hashlib
from datetime import UTC, datetime
from typing import Annotated, Self, override
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import Receive, Scope, Send

from ...accounts.administrators import AdministratorRepository, AdministratorService
from ...admin.services import AdminService, MetricsSnapshot
from ...meetings.monitoring import MeetingMetadata
from ...processing.enums import JobStatus, JobType
from ...processing.monitoring import JobFilter, JobMonitoring, JobSnapshot
from ...shared.errors import Failure, UseCaseError
from ...shared.pagination import ListCursor
from ..accounts.auth import BrowserUser
from ..composition import Observations, Session
from ..core.errors import error_responses
from ..core.pagination import list_page, list_window
from ..core.schemas import Output, Page, PageQuery


class MonitoringRoute(APIRoute):
    @override
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().handle(scope, receive, send)
        except SQLAlchemyError:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None


router = APIRouter(
    route_class=MonitoringRoute,
    tags=["admin"],
    responses=error_responses(
        {
            401: "Browser session required",
            403: "INSUFFICIENT_ROLE: administrator permission required",
            422: "Invalid filter or cursor",
            503: "Monitoring database unavailable",
        }
    ),
)


async def require_administrator(user: BrowserUser, session: Session) -> None:
    await AdministratorService(AdministratorRepository(session)).require(user.id)


Administrator = Annotated[None, Depends(require_administrator)]


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
    administrator: Administrator,
    session: Session,
    response: Response,
) -> Page[JobSnapshot]:
    del administrator
    scope = (
        "admin-jobs:"
        + hashlib.sha256(query.model_dump_json(exclude={"cursor", "limit"}).encode()).hexdigest()
    )
    filters = JobFilter(
        query.workspace_id, query.job_type, query.status, query.created_from, query.created_to
    )
    items = await JobMonitoring(session, MeetingMetadata(session)).jobs(
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
        "Administrator-only logical-job aggregates and bounded last-good "
        "host/runtime observations. Sources become stale after 30 seconds, "
        "unavailable after 90, and expire after 5 minutes. Unknown "
        "measurements remain null. Anthropic notes are external; local notes "
        "worker state follows observed Ollama execution and source freshness."
    ),
)
async def metrics(
    administrator: Administrator, session: Session, store: Observations, response: Response
) -> MetricsRead:
    del administrator
    result = await AdminService(JobMonitoring(session, MeetingMetadata(session)), store).metrics(
        datetime.now(UTC)
    )

    response.headers["Cache-Control"] = "no-store"
    return MetricsRead.model_validate(result.model_dump())
