from typing import ClassVar, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExportSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_EXPORT_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    public_origin: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:3000"),
        description="Canonical public HTTP(S) origin for authenticated original-transcript links",
    )

    @model_validator(mode="after")
    def origin_only(self) -> Self:
        url = self.public_origin
        if (
            url.username is not None
            or url.password is not None
            or url.query is not None
            or url.fragment is not None
            or url.path not in (None, "/")
        ):
            raise ValueError("Public origin must not contain credentials, path, query or fragment")
        return self
