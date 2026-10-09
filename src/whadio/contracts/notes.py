from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints

from .common import ContractModel, GlossaryEntry, JobMessage, Transcript

MAX_CONTEXT_MEETINGS: Final = 20

MeetingName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$"),
    Field(description="Meeting name: one line of at most 200 characters"),
]


class NotesPreset(StrEnum):
    SUMMARY = "summary"
    DETAILED = "detailed"
    INTERVIEW = "interview"


class NotesProvider(StrEnum):
    WHADIO = "whadio"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


class MeetingBrief(ContractModel):
    name: MeetingName | None = Field(
        description="Name a member gave the meeting; null while the name is generated"
    )
    recorded_at: AwareDatetime = Field(description="When the meeting was recorded")


class ContextMeeting(ContractModel):
    meeting_id: UUID = Field(description="Meeting of the same folder that may serve as context")
    name: MeetingName
    recorded_at: AwareDatetime = Field(description="When the meeting was recorded")
    transcript: Transcript = Field(description="Current revision of its transcript")


class NotesRequested(JobMessage):
    type: Literal["notes_requested"] = Field(default="notes_requested", description="Message type")
    preset: NotesPreset = Field(description="Preset that defines the sections of the notes")
    meeting: MeetingBrief = Field(description="The meeting to write notes for")
    transcript: Transcript = Field(description="Current revision of the meeting's transcript")
    context: tuple[ContextMeeting, ...] = Field(
        max_length=MAX_CONTEXT_MEETINGS,
        description="Readable meetings of the same folder, the restricted ones already left out "
        "(FR-019); the worker may use only some of them",
    )
    glossary: tuple[GlossaryEntry, ...] = Field(description="The workspace glossary")


class NotesReady(JobMessage):
    type: Literal["notes_ready"] = Field(default="notes_ready", description="Message type")
    finished_at: AwareDatetime = Field(description="When the worker finished the job")
    preset: NotesPreset = Field(description="Preset the notes follow")
    provider: NotesProvider = Field(description="Who ran the language model")
    model_name: str = Field(min_length=1, description="Language model that wrote the notes")
    content: str = Field(min_length=1, description="The notes in Markdown, without the title")
    proposed_name: MeetingName
    context_meeting_ids: tuple[UUID, ...] = Field(
        description="Context meetings the notes were actually written with (FR-020)"
    )


class NotesFailure(StrEnum):
    TRANSCRIPT_TOO_LONG = "transcript_too_long"
    PROVIDER_AUTH_FAILED = "provider_auth_failed"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REFUSED = "provider_refused"
    INVALID_OUTPUT = "invalid_output"
    TIMED_OUT = "timed_out"
    INTERNAL_ERROR = "internal_error"

    @property
    def retryable(self) -> bool:
        return self in _RETRYABLE_NOTES_FAILURES


_RETRYABLE_NOTES_FAILURES = frozenset(
    {
        NotesFailure.PROVIDER_RATE_LIMITED,
        NotesFailure.PROVIDER_UNAVAILABLE,
        NotesFailure.INVALID_OUTPUT,
        NotesFailure.TIMED_OUT,
        NotesFailure.INTERNAL_ERROR,
    }
)


class NotesFailed(JobMessage):
    type: Literal["notes_failed"] = Field(default="notes_failed", description="Message type")
    finished_at: AwareDatetime = Field(description="When the worker gave up on this attempt")
    reason: NotesFailure = Field(
        description="Why the attempt failed; never carries transcript or provider response text"
    )
