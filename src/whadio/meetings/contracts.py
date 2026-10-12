from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from ..accounts.enums import LlmProvider, NotesTemplate
from .enums import ProcessingFailure, ProcessingState
from .models import (
    Meeting,
    Note,
    NoteContextMeeting,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)


@dataclass(frozen=True)
class EvictionNotice:
    meeting_id: UUID
    triggering_meeting_id: UUID
    recipient_id: UUID
    meeting_name: str | None
    occurred_at: datetime


class IEvictionNotifier(Protocol):
    async def enqueue(self, notice: EvictionNotice) -> None:
        """Reserve a durable, deduplicated notice in the caller's transaction.

        Delivery must use this pre-deletion recipient/title snapshot, never reauthorize
        against the deleted meeting. Failure must abort ingest; do not send before commit.
        """
        ...


@dataclass(frozen=True)
class MeetingFilter:
    workspace_id: UUID
    folder_id: UUID | None = None
    name: str | None = None
    recorded_from: datetime | None = None
    recorded_to: datetime | None = None
    limit: int | None = None
    after: tuple[datetime, UUID] | None = None


@dataclass(frozen=True)
class TranscriptVersion:
    transcript: Transcript
    revision: TranscriptRevision
    original_revision_id: UUID
    is_edited: bool
    speakers: list[Speaker]
    segments: list[TranscriptSegment]


@dataclass(frozen=True)
class NoteVersion:
    note: Note
    context: list[NoteContextMeeting]
    is_current: bool = True


@dataclass(frozen=True)
class ContextReference:
    meeting_id: UUID
    name: str


@dataclass(frozen=True)
class InitialSpeaker:
    key: str
    display_name: str


@dataclass(frozen=True)
class InitialSegment:
    speaker_key: str | None
    start_seconds: Decimal
    end_seconds: Decimal
    text: str


@dataclass(frozen=True)
class InitialTranscript:
    job_id: UUID
    language: str
    model_name: str
    speakers: tuple[InitialSpeaker, ...]
    segments: tuple[InitialSegment, ...]


@dataclass(frozen=True)
class ProcessingUpdate:
    state: ProcessingState
    failure: ProcessingFailure | None = None
    regeneration_count: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class QueuedNotes:
    job_id: UUID
    meeting_id: UUID
    preset: NotesTemplate
    provider: LlmProvider
    created_at: datetime


@dataclass(frozen=True)
class PipelineMeeting:
    meeting: Meeting
    workspace_id: UUID


@dataclass(frozen=True)
class ContextTranscript:
    meeting: Meeting
    transcript: TranscriptVersion
