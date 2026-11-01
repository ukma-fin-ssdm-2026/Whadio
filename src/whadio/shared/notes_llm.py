from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicLlm(BaseModel):
    reported_provider: ClassVar[Literal["anthropic"]] = "anthropic"

    provider: Literal["anthropic"] = Field(
        default="anthropic", description="Claude through the Anthropic API"
    )
    model: str = Field(default="claude-sonnet-5-5", description="Claude model that writes notes")


class OllamaLlm(BaseModel):
    reported_provider: ClassVar[Literal["whadio"]] = "whadio"

    provider: Literal["ollama"] = Field(description="A model served by a self-hosted Ollama")
    model: str = Field(min_length=1, description="Tag of a pulled model, such as gemma4:12b-it-qat")


type NotesLlm = Annotated[AnthropicLlm | OllamaLlm, Field(discriminator="provider")]


class _NotesGroup(BaseModel):
    llm: NotesLlm = Field(description="The language model that writes notes")


class NotesLlmSettings(BaseSettings):
    # The dotenv source collects the whole group, so an error's input would show the API key.
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    notes: _NotesGroup = Field(description="The part of the notes settings the web reports")


def load_notes_llm() -> NotesLlm:
    return NotesLlmSettings.model_validate({}).notes.llm
