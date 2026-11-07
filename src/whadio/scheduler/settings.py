from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..processing.settings import JobRecoverySettings
from ..shared.storage import ObjectStorageSettings


class SchedulerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    storage: ObjectStorageSettings = Field(description="Recording storage for cleanup.")
    retention_interval_seconds: float = Field(
        default=60, gt=0, description="Seconds between retention passes."
    )
    job_recovery: JobRecoverySettings = Field(
        default_factory=JobRecoverySettings,
        description="When a processing job that no worker finished goes back to the queue.",
    )
