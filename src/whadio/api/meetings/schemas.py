from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from fastapi import Path
from pydantic import Field, model_validator

from ..accounts.schemas import Preset, Provider
from ..core.schemas import DisplayText, Input, Output, PageQuery, UtcDatetime

MEETING_ID_EXAMPLE = "5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9"
FOLDER_ID_EXAMPLE = "e8f7d6c5-b4a3-4291-8f7e-6d5c4b3a2918"


class SourceType(StrEnum):
    EXTENSION = "extension"
    UPLOAD = "upload"


class RecordingStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class ProcessingState(StrEnum):
    RECORDING = "recording"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class AccessMode(StrEnum):
    WORKSPACE = "workspace"
    RESTRICTED = "restricted"


class RevisionType(StrEnum):
    ORIGINAL = "original"
    EDITED = "edited"


MeetingId = Annotated[UUID, Path(description="Meeting identifier", examples=[MEETING_ID_EXAMPLE])]
FolderId = Annotated[UUID, Path(description="Folder identifier", examples=[FOLDER_ID_EXAMPLE])]
MeetingName = Annotated[
    DisplayText,
    Field(min_length=1, max_length=200, description="Meeting name", examples=["Sprint 12 review"]),
]

# --- Meetings ---


class MeetingListQuery(PageQuery):
    folder_id: UUID | None = Field(default=None, description="Only meetings in this folder")
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Case-insensitive part of the meeting name",
    )
    recorded_from: UtcDatetime | None = Field(
        default=None, description="Recorded at or after this instant (inclusive)"
    )
    recorded_to: UtcDatetime | None = Field(
        default=None, description="Recorded before this instant (exclusive)"
    )

    @model_validator(mode="after")
    def _range_ordered(self) -> Self:
        if (
            self.recorded_from is not None
            and self.recorded_to is not None
            and self.recorded_to <= self.recorded_from
        ):
            raise ValueError("`recorded_to` must be later than `recorded_from`")
        return self


class MeetingSummary(Output):
    id: UUID = Field(description="Meeting identifier", examples=[MEETING_ID_EXAMPLE])
    workspace_id: UUID = Field(description="Workspace of the meeting")
    folder_id: UUID = Field(description="Folder of the meeting", examples=[FOLDER_ID_EXAMPLE])
    name: str = Field(description="Meeting name", examples=["Sprint 12 review"])
    name_is_generated: bool = Field(
        description="True while the name is the system's proposal; prompt the user to "
        "confirm or rename it"
    )
    recorded_at: datetime = Field(description="When the meeting was recorded; not editable")
    processing_state: ProcessingState = Field(
        description="Pipeline state; poll the meeting until `processed` or `failed`"
    )
    recording_status: RecordingStatus = Field(
        description="`partial` when the capture ended without a stop, e.g. a closed tab"
    )
    source_type: SourceType = Field(description="Recorded by the extension or uploaded")
    duration_seconds: int | None = Field(description="Length of the recording, once known")
    access_mode: AccessMode = Field(
        description="`restricted` meetings are visible only to the selected members"
    )


class MeetingRead(MeetingSummary):
    created_by_user_id: UUID = Field(description="Member who recorded or uploaded it")
    created_at: datetime = Field(description="When the meeting was created in Whadio")
    failure_reason: str | None = Field(
        description="Why processing failed, when `processing_state` is `failed`; never "
        "contains meeting content",
        examples=[None],
    )
    is_edited: bool = Field(description="Whether the transcript was edited")
    recording_available: bool = Field(
        description="Whether `GET /recording` can return a playback link"
    )
    recording_delete_after: datetime = Field(
        description="When the recording is deleted under retention; transcript and notes stay"
    )
    consent_confirmed_at: datetime | None = Field(
        description="When the recorder confirmed participant consent (extension recordings)"
    )


class MeetingUpdate(Input):
    name: MeetingName | None = Field(default=None, description="New meeting name")
    folder_id: UUID | None = Field(
        default=None, description="Folder of the same workspace to move the meeting to"
    )

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.name is None and self.folder_id is None:
            raise ValueError("give at least one of `name` and `folder_id`")
        return self


# --- Transcripts ---


class RevisionRead(Output):
    id: UUID = Field(description="Revision identifier")
    revision_type: RevisionType = Field(
        description="`original` is the recognised text, kept forever; `edited` revisions follow it"
    )
    created_at: datetime = Field(description="When the revision was made")
    edited_by_user_id: UUID | None = Field(description="Editor; null for the original")
    is_current: bool = Field(description="Whether this is the revision shown by default")


class SpeakerRead(Output):
    id: UUID = Field(description="Speaker label identifier, specific to this revision")
    display_name: str = Field(description="Label shown for the speaker", examples=["Alice"])
    is_unnamed: bool = Field(description="Whether the label is a placeholder like `Speaker 2`")


class SegmentRead(Output):
    id: UUID = Field(description="Segment identifier, specific to this revision")
    speaker_id: UUID | None = Field(description="Speaker label of the segment, if any")
    start_seconds: float = Field(ge=0, description="Start offset in seconds", examples=[12.4])
    end_seconds: float = Field(ge=0, description="End offset in seconds", examples=[18.9])
    text: str = Field(description="Recognised or edited text")


class TranscriptRead(Output):
    meeting_id: UUID = Field(description="Meeting of the transcript")
    language: str = Field(description="Main language", examples=["uk"])
    model_name: str = Field(description="Recognition model", examples=["parakeet-tdt-0.6b-v3"])
    revision: RevisionRead
    original_revision_id: UUID = Field(description="The original, always reachable")
    is_edited: bool = Field(description="Whether any edited revision exists")
    has_unnamed_speakers: bool = Field(
        description="Whether some speakers still have placeholder labels"
    )
    speakers: list[SpeakerRead] = Field(description="Speaker labels of this revision")
    segments: list[SegmentRead] = Field(description="Segments in time order")


# --- Notes ---


class ContextMeetingRead(Output):
    meeting_id: UUID | None = Field(
        description="Meeting used as context; null once that meeting was deleted"
    )
    name: str = Field(description="Its name when the notes were generated")


class NoteRead(Output):
    id: UUID = Field(description="Notes identifier")
    preset: Preset = Field(description="Preset the notes follow")
    provider: Provider = Field(description="Model provider that wrote them")
    model_name: str = Field(description="Model that wrote them", examples=["gemma4:12b-it-qat"])
    content: str = Field(description="Notes in Markdown")
    created_at: datetime = Field(description="When they were generated")
    created_by_user_id: UUID | None = Field(
        description="Who requested a regeneration; null for the automatic first notes"
    )
    is_current: bool = Field(
        description="The notes shown by default; earlier versions stay readable"
    )
    context_meetings: list[ContextMeetingRead] = Field(
        description="Meetings of the same folder used as context"
    )
