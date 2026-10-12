from uuid import UUID

from ...meetings.contracts import NoteVersion, TranscriptVersion
from ...meetings.models import Meeting
from ..accounts.schemas import Preset, Provider
from .schemas import (
    AccessMode,
    ContextMeetingRead,
    MeetingRead,
    MeetingSummary,
    NoteRead,
    ProcessingState,
    RecordingStatus,
    RevisionRead,
    RevisionType,
    SegmentRead,
    SourceType,
    SpeakerRead,
    TranscriptRead,
)


def meeting_summary(meeting: Meeting, workspace_id: UUID) -> MeetingSummary:
    return MeetingSummary(
        id=meeting.meeting_id,
        workspace_id=workspace_id,
        folder_id=meeting.folder_id,
        name=meeting.name,
        name_is_generated=meeting.name_is_generated,
        recorded_at=meeting.recorded_at,
        processing_state=ProcessingState(meeting.processing_state),
        recording_status=RecordingStatus(meeting.recording_status),
        source_type=SourceType(meeting.source_type),
        duration_seconds=meeting.duration_seconds,
        access_mode=AccessMode(meeting.access_mode),
    )


def meeting_read(meeting: Meeting, workspace_id: UUID, *, is_edited: bool) -> MeetingRead:
    return MeetingRead(
        id=meeting.meeting_id,
        workspace_id=workspace_id,
        folder_id=meeting.folder_id,
        name=meeting.name,
        name_is_generated=meeting.name_is_generated,
        recorded_at=meeting.recorded_at,
        processing_state=ProcessingState(meeting.processing_state),
        recording_status=RecordingStatus(meeting.recording_status),
        source_type=SourceType(meeting.source_type),
        duration_seconds=meeting.duration_seconds,
        access_mode=AccessMode(meeting.access_mode),
        created_by_user_id=meeting.created_by_user_id,
        created_at=meeting.created_at,
        failure_reason=meeting.failure_reason,
        is_edited=is_edited,
        recording_available=meeting.storage_path is not None
        and meeting.recording_deleted_at is None,
        recording_delete_after=meeting.recording_delete_after,
        consent_confirmed_at=meeting.consent_confirmed_at,
    )


def transcript_read(version: TranscriptVersion) -> TranscriptRead:
    speakers = [
        SpeakerRead(
            id=item.speaker_id,
            display_name=item.display_name,
            is_unnamed=item.display_name.startswith("Speaker "),
        )
        for item in version.speakers
    ]
    return TranscriptRead(
        meeting_id=version.transcript.meeting_id,
        language=version.transcript.language,
        model_name=version.transcript.model_name,
        original_revision_id=version.original_revision_id,
        is_edited=version.is_edited,
        has_unnamed_speakers=any(item.is_unnamed for item in speakers),
        revision=RevisionRead(
            id=version.revision.revision_id,
            revision_type=RevisionType(version.revision.revision_type),
            created_at=version.revision.created_at,
            edited_by_user_id=version.revision.edited_by_user_id,
            is_current=version.transcript.current_revision_id == version.revision.revision_id,
        ),
        speakers=speakers,
        segments=[
            SegmentRead(
                id=item.segment_id,
                speaker_id=item.speaker_id,
                start_seconds=float(item.start_time_seconds),
                end_seconds=float(item.end_time_seconds),
                text=item.text,
            )
            for item in version.segments
        ],
    )


def notes_read(versions: list[NoteVersion]) -> list[NoteRead]:
    return [
        NoteRead(
            id=version.note.note_id,
            preset=Preset(version.note.template),
            provider=Provider(version.note.provider.lower()),
            model_name=version.note.model_name,
            content=version.note.content,
            created_at=version.note.created_at,
            created_by_user_id=version.note.created_by_user_id,
            is_current=version.is_current,
            context_meetings=[
                ContextMeetingRead(
                    meeting_id=item.context_meeting_id, name=item.context_meeting_name_snapshot
                )
                for item in version.context
            ],
        )
        for version in versions
    ]
