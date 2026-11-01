from typing import ClassVar, Self

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PublicUrlSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    public_url: HttpUrl | None = Field(
        default=None,
        description="Public application base URL, including an optional deployment path; "
        "used in exports and required for invitation links and with an SMTP relay",
    )
    api_public_url: HttpUrl | None = Field(
        default=None,
        description="Public API deployment base before /api/v1, including an optional path; "
        "defaults to the public application base",
    )

    @model_validator(mode="after")
    def public_application_base(self) -> Self:
        for url in (self.public_url, self.api_public_url):
            if url is not None and (
                url.username is not None
                or url.password is not None
                or url.query is not None
                or url.fragment is not None
            ):
                raise ValueError("Public URL must not contain credentials, query or fragment")
        return self
