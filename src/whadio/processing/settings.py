from datetime import timedelta

from pydantic import BaseModel, Field


class JobRecoverySettings(BaseModel):
    unstarted_limit: timedelta = Field(
        default=timedelta(days=2),
        gt=timedelta(0),
        description="How long a published job may wait for a worker to start it before it is "
        "published again with one more attempt counted",
    )
