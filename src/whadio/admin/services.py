from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..processing.monitoring import IJobMonitoring, JobCounts


class MetricsSnapshot(BaseModel):
    generated_at: datetime = Field(description="UTC assembly time for the job counts")
    status: Literal["ok"] = Field(description="Job counts were read successfully")
    jobs: list[JobCounts] = Field(description="Logical-job aggregates from PostgreSQL")


class AdminService:
    def __init__(self, jobs: IJobMonitoring) -> None:
        self._jobs: IJobMonitoring = jobs

    async def metrics(self, now: datetime) -> MetricsSnapshot:
        return MetricsSnapshot(generated_at=now, status="ok", jobs=await self._jobs.counts(now))
