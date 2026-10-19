from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceSettings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token_hash: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 of the source bearer token; never the token itself",
    )
    kind: Literal["host", "runtime"] = Field(description="Scope this credential may publish")
    runtime: Literal["asr", "notes"] | None = Field(
        default=None, description="Allowed runtime identity for a runtime source"
    )

    @model_validator(mode="after")
    def scope_matches(self) -> Self:
        if (self.kind == "runtime") != (self.runtime is not None):
            raise ValueError("Runtime scope requires exactly one allowed runtime identity")
        return self


SourceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


class AdminSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_ADMIN_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    sources: dict[SourceId, SourceSettings] = Field(
        default_factory=dict[str, SourceSettings],
        max_length=32,
        description="Opaque source aliases with source-scoped credential hashes and allowed scope",
    )
