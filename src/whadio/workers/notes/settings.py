from datetime import timedelta
from typing import ClassVar

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...shared.broker import BrokerSettings
from ...shared.logs import LogLevel
from .claude import Effort


class NotesSettings(BaseModel):
    api_key: SecretStr = Field(min_length=1, description="Anthropic API key of the deployment")
    model: str = Field(default="claude-sonnet-5-5", description="Claude model that writes notes")
    effort: Effort = Field(default="medium", description="How much the model thinks per answer")
    max_output_tokens: int = Field(
        default=16_000, ge=1_024, description="Upper bound of one answer, thinking included"
    )
    max_input_tokens: int = Field(
        default=100_000,
        ge=1_000,
        description="Budget for the prompt; context meetings that do not fit are left out",
    )
    chars_per_token: float = Field(
        default=2.5, gt=0, description="Characters per token assumed when estimating the prompt"
    )
    concurrency: int = Field(default=4, ge=1, description="Jobs handled at the same time")
    job_timeout: timedelta = Field(
        default=timedelta(minutes=10), description="Time after which a job is given up"
    )
    shutdown_grace: timedelta = Field(
        default=timedelta(minutes=1), description="Time running jobs get to finish on shutdown"
    )


class NotesWorkerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    log_level: LogLevel = Field(default="INFO", description="Lowest level of logged records")
    broker: BrokerSettings = Field(description="Connection to RabbitMQ")
    notes: NotesSettings = Field(description="The language model and the job limits")


def load_notes_worker_settings() -> NotesWorkerSettings:
    # Pyright gives a BaseSettings subclass a constructor that demands every field, although the
    # settings sources supply them; model_validate reads the same sources.
    return NotesWorkerSettings.model_validate({})
