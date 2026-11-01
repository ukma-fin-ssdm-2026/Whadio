from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..shared.storage import ObjectStorageSettings


class MeetingSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    storage: ObjectStorageSettings | None = Field(
        default=None, description="Recording upload and playback storage."
    )
    meetings_hosted: bool = Field(
        default=False, description="Enforce the hosted limit of 1000 meetings per workspace owner."
    )
