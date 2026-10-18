from datetime import timedelta
from email.errors import HeaderParseError
from email.headerregistry import Address
from typing import ClassVar, Self

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SmtpSettings(BaseModel):
    host: str = Field(min_length=1, description="Hostname of the SMTP relay")
    port: int = Field(default=587, ge=1, le=65535, description="TCP port of the SMTP relay")
    starttls: bool = Field(
        default=True, description="Upgrade the connection with STARTTLS before authenticating"
    )
    username: str | None = Field(
        default=None, min_length=1, description="Relay login; no authentication when unset"
    )
    password: SecretStr | None = Field(
        default=None, description="Relay password; set exactly when the username is"
    )
    from_address: str = Field(description="Envelope and header sender, such as noreply@host")
    timeout: timedelta = Field(
        default=timedelta(seconds=30),
        gt=timedelta(0),
        description="Time after which a relay that does not answer is given up",
    )

    # Not EmailStr: it refuses special-use domains such as .local, which self-hosted relays use.
    @field_validator("from_address")
    @classmethod
    def _is_an_address(cls, value: str) -> str:
        try:
            Address(addr_spec=value)
        except (HeaderParseError, ValueError) as error:
            raise ValueError("from_address must be an email address") from error
        return value

    @model_validator(mode="after")
    def _credentials_are_complete_and_encrypted(self) -> Self:
        if (self.username is None) != (self.password is None):
            raise ValueError("set both the SMTP username and password, or neither")
        if self.username is not None and not self.starttls:
            raise ValueError("SMTP credentials are sent only over STARTTLS")
        return self


class OutboxSettings(BaseModel):
    batch_size: int = Field(
        default=50, ge=1, le=1000, description="Most notices sent in one scheduler pass"
    )
    retry_backoff: timedelta = Field(
        default=timedelta(minutes=1),
        gt=timedelta(0),
        description="Wait after the first attempt before a notice is due again; it doubles with "
        "each further attempt. Keep it longer than a send can take: a notice whose send outlasts "
        "it may be sent twice",
    )
    max_retry_backoff: timedelta = Field(
        default=timedelta(hours=6),
        le=timedelta(days=7),
        description="Longest wait between two delivery attempts",
    )
    max_attempts: int = Field(
        default=16,
        ge=1,
        le=100,
        description="Delivery attempts after which a notice is given up and no longer sent",
    )
    retention: timedelta = Field(
        default=timedelta(days=7),
        gt=timedelta(0),
        description="How long a sent notice is kept, and a given-up one after it was reserved",
    )

    @model_validator(mode="after")
    def _backoff_cap_is_reachable(self) -> Self:
        if self.max_retry_backoff < self.retry_backoff:
            raise ValueError("max_retry_backoff must not be shorter than retry_backoff")
        return self


class NotificationSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    smtp: SmtpSettings | None = Field(
        default=None,
        description="The mail relay; without it no notification is sent and none is refused "
        "(FR-047)",
    )
    public_url: HttpUrl = Field(
        description="Address the web application is reached at; mail links start with it"
    )
    outbox: OutboxSettings = Field(
        default_factory=OutboxSettings, description="Delivery of the reserved notices"
    )


def load_notification_settings() -> NotificationSettings:
    # Pyright gives a BaseSettings subclass a constructor that demands every field, although the
    # settings sources supply them; model_validate reads the same sources.
    return NotificationSettings.model_validate({})
