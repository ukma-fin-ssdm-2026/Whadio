from enum import StrEnum
from typing import Annotated, ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

LanguageCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z]{2,3}$"),
    Field(description="ISO 639 language code, such as `uk` or `en`", examples=["uk"]),
]


class ContractModel(BaseModel):
    # Messages are only ever read with `model_validate_json`, where strict mode still accepts UUID,
    # datetime and enum strings.
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, frozen=True, extra="forbid")


class JobKind(StrEnum):
    TRANSCRIPTION = "transcription"
    NOTES = "notes"


class JobMessage(ContractModel):
    job_id: UUID = Field(description="Processing job this message belongs to")
    meeting_id: UUID = Field(description="Meeting the job processes")


class GlossaryEntry(ContractModel):
    term: str = Field(min_length=1, description="Term as it may be heard in speech")
    preferred_form: str = Field(min_length=1, description="Spelling the workspace wants used")
    description: str = Field(description="What the term means; may be empty")


class Segment(ContractModel):
    start_seconds: float = Field(ge=0, description="Start of the segment from the recording start")
    end_seconds: float = Field(gt=0, description="End of the segment from the recording start")
    speaker: str | None = Field(
        description="Label of the speaker, one of the transcript's `speakers`; null if unknown"
    )
    text: str = Field(min_length=1, description="Recognised text of the segment")

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("a segment must end after it starts")
        return self


class Transcript(ContractModel):
    language: LanguageCode
    speakers: tuple[str, ...] = Field(
        description="Speaker labels in order of first appearance, such as `Speaker 1`"
    )
    segments: tuple[Segment, ...] = Field(description="Segments in order of their start")

    @model_validator(mode="after")
    def _speakers_are_known(self) -> Self:
        if len(set(self.speakers)) != len(self.speakers):
            raise ValueError("speaker labels must be unique")
        known = set(self.speakers)
        if any(s.speaker is not None and s.speaker not in known for s in self.segments):
            raise ValueError("every segment's speaker must be one of `speakers`")
        return self
