from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl

from .common import ContractModel, GlossaryEntry, JobMessage, LanguageCode, Transcript


class AudioLink(ContractModel):
    url: HttpUrl = Field(description="Presigned GET URL of the recording, scoped to one object")
    expires_at: AwareDatetime = Field(description="When the URL stops working")


class TranscriptionRequested(JobMessage):
    type: Literal["transcription_requested"] = Field(
        default="transcription_requested", description="Message type"
    )
    audio: AudioLink = Field(description="Where to download the recording")
    language: LanguageCode | None = Field(
        description="Expected language of the meeting; null to detect it"
    )
    glossary: tuple[GlossaryEntry, ...] = Field(
        description="The workspace glossary, supplied to recognition (FR-029)"
    )


class TranscriptReady(JobMessage):
    type: Literal["transcript_ready"] = Field(
        default="transcript_ready", description="Message type"
    )
    finished_at: AwareDatetime = Field(description="When the worker finished the job")
    model_name: str = Field(min_length=1, description="Speech recognition model that was used")
    duration_seconds: float = Field(ge=0, description="Duration of the recording")
    transcript: Transcript = Field(description="The original transcript")


class TranscriptionFailure(StrEnum):
    AUDIO_LINK_EXPIRED = "audio_link_expired"
    AUDIO_NOT_FOUND = "audio_not_found"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    AUDIO_TOO_LARGE = "audio_too_large"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    AUDIO_TOO_LONG = "audio_too_long"
    TIMED_OUT = "timed_out"
    WORKER_CRASHED = "worker_crashed"
    INTERNAL_ERROR = "internal_error"

    @property
    def retryable(self) -> bool:
        return self in _RETRYABLE_TRANSCRIPTION_FAILURES


_RETRYABLE_TRANSCRIPTION_FAILURES = frozenset(
    {
        TranscriptionFailure.AUDIO_LINK_EXPIRED,
        TranscriptionFailure.STORAGE_UNAVAILABLE,
        TranscriptionFailure.WORKER_CRASHED,
        TranscriptionFailure.INTERNAL_ERROR,
    }
)


class TranscriptionFailed(JobMessage):
    type: Literal["transcription_failed"] = Field(
        default="transcription_failed", description="Message type"
    )
    finished_at: AwareDatetime = Field(description="When the worker gave up on this attempt")
    reason: TranscriptionFailure = Field(
        description="Why the attempt failed; never carries recording or transcript content"
    )
