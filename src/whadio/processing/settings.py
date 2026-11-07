from datetime import timedelta

from pydantic import BaseModel, Field


class JobRecoverySettings(BaseModel):
    unstarted_limit: timedelta = Field(
        default=timedelta(days=2),
        gt=timedelta(0),
        description="How long a published job may wait for a worker to start it before it is "
        "published again with one more attempt counted",
    )
    transcription_running_limit: timedelta = Field(
        default=timedelta(hours=5),
        gt=timedelta(0),
        description="How long a transcription job may run before it is published again; it must "
        "exceed the ASR worker's startup timeout plus its job timeout, plus the 5-minute margin of "
        "its consumer timeout",
    )
    notes_running_limit: timedelta = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
        description="How long a notes job may run before it is published again; it must exceed "
        "the notes worker's job timeout plus the 5-minute margin of its consumer timeout",
    )
