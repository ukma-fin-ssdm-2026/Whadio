from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    HttpUrl,
    JsonValue,
    SecretStr,
    Tag,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...shared.broker import BrokerSettings
from ...shared.logs import LogLevel
from .claude import Effort

_DEFAULT_PROVIDER: Final = "anthropic"
_MIN_PROMPT_TOKENS: Final = 1_000


class AnthropicSettings(BaseModel):
    provider: Literal["anthropic"] = Field(
        default="anthropic", description="Claude through the Anthropic API"
    )
    api_key: SecretStr = Field(min_length=1, description="Anthropic API key of the deployment")
    model: str = Field(default="claude-sonnet-5-5", description="Claude model that writes notes")
    effort: Effort = Field(default="medium", description="How much the model thinks per answer")


class OllamaSettings(BaseModel):
    provider: Literal["ollama"] = Field(description="A model served by a self-hosted Ollama")
    base_url: HttpUrl = Field(
        default=HttpUrl("http://localhost:11434"), description="Address of the Ollama server"
    )
    model: str = Field(min_length=1, description="Tag of a pulled model, such as gemma3:12b")
    num_ctx: int = Field(
        default=32_768,
        ge=2_048,
        description="Context window in tokens, prompt and answer together; a job that does not "
        "fit fails as too long",
    )
    keep_alive: timedelta = Field(
        default=timedelta(minutes=5),
        ge=timedelta(0),
        description="How long the model stays in memory after a request",
    )


# A callable discriminator lets an unset provider mean Anthropic; `discriminator="provider"`
# would demand the tag.
def _provider_of(
    settings: Mapping[str, JsonValue] | AnthropicSettings | OllamaSettings,
) -> str | None:
    if isinstance(settings, AnthropicSettings | OllamaSettings):
        return settings.provider
    provider = settings.get("provider", _DEFAULT_PROVIDER)
    return provider if isinstance(provider, str) else None


type LlmSettings = Annotated[
    Annotated[AnthropicSettings, Tag("anthropic")] | Annotated[OllamaSettings, Tag("ollama")],
    Discriminator(_provider_of),
]


class NotesSettings(BaseModel):
    llm: LlmSettings = Field(description="The language model that writes notes")
    max_output_tokens: int = Field(
        default=16_000, ge=1_024, description="Upper bound of one answer, thinking included"
    )
    max_input_tokens: int = Field(
        default=100_000,
        ge=_MIN_PROMPT_TOKENS,
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

    @model_validator(mode="after")
    def _window_leaves_room_for_a_prompt(self) -> Self:
        if (
            isinstance(self.llm, OllamaSettings)
            and self.llm.num_ctx - self.max_output_tokens < _MIN_PROMPT_TOKENS
        ):
            message = (
                f"llm.num_ctx must exceed max_output_tokens by at least {_MIN_PROMPT_TOKENS} "
                "tokens to leave room for the prompt"
            )
            raise ValueError(message)
        return self

    @property
    def max_prompt_tokens(self) -> int:
        match self.llm:
            case AnthropicSettings():
                return self.max_input_tokens
            case OllamaSettings(num_ctx=num_ctx):
                return min(self.max_input_tokens, num_ctx - self.max_output_tokens)


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
