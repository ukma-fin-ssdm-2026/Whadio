from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..shared.storage import ObjectStorageSettings


class SchedulerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    storage: ObjectStorageSettings = Field(description="Recording storage for cleanup.")
    retention_interval_seconds: float = Field(
        default=60, gt=0, description="Seconds between retention passes."
    )
