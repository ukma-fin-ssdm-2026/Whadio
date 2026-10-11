from typing import Annotated, Final, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from .common import JobKind, JobMessage
from .notes import NotesFailed, NotesReady
from .transcription import TranscriptionFailed, TranscriptReady


class JobStarted(JobMessage):
    type: Literal["job_started"] = Field(default="job_started", description="Message type")
    kind: JobKind = Field(description="Kind of the job that started")
    started_at: AwareDatetime = Field(description="When a worker started the attempt")


ProcessingResult = Annotated[
    JobStarted | TranscriptReady | TranscriptionFailed | NotesReady | NotesFailed,
    Field(discriminator="type"),
]

_RESULTS: Final = TypeAdapter[ProcessingResult](ProcessingResult)


def parse_result(body: bytes) -> ProcessingResult:
    return _RESULTS.validate_json(body)
