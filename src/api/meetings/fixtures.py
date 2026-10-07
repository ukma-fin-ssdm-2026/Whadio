from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.fixtures import ALICE, PERSONAL_WORKSPACE_ID, TEAM_WORKSPACE_ID
from ..accounts.schemas import Preset, Provider
from ..core.errors import ApiError, ErrorCode, not_found
from .models import Folder, Meeting
from .schemas import (
    AccessMode,
    ContextMeetingRead,
    MeetingRead,
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

SPRINT_FOLDER_ID: Final = UUID("e8f7d6c5-b4a3-4291-8f7e-6d5c4b3a2918")
SPRINT_12_MEETING_ID: Final = UUID("5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9")
SPRINT_11_MEETING_ID: Final = UUID("8c7b6a59-4d3e-4f2a-b1c0-d9e8f7a6b5c4")
DESIGN_SYNC_MEETING_ID: Final = UUID("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
PERSONAL_FOLDER_ID: Final = UUID("2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e")
TEAM_DEFAULT_FOLDER_ID: Final = UUID("9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a")
RETENTION: Final = timedelta(days=90)


def _meeting(
    meeting_id: UUID,
    workspace_id: UUID,
    folder_id: UUID,
    name: str,
    recorded_at: datetime,
    state: ProcessingState,
    source: SourceType,
) -> MeetingRead:
    is_extension = source is SourceType.EXTENSION
    return MeetingRead(
        id=meeting_id,
        workspace_id=workspace_id,
        folder_id=folder_id,
        name=name,
        name_is_generated=False,
        recorded_at=recorded_at,
        processing_state=state,
        recording_status=RecordingStatus.COMPLETE,
        source_type=source,
        duration_seconds=None if state is ProcessingState.QUEUED else 2_730,
        access_mode=AccessMode.WORKSPACE,
        created_by_user_id=ALICE.id,
        created_at=recorded_at,
        failure_reason=None,
        is_edited=False,
        recording_available=True,
        recording_delete_after=recorded_at + RETENTION,
        consent_confirmed_at=recorded_at if is_extension else None,
    )


_MEETINGS: Final = (
    _meeting(
        DESIGN_SYNC_MEETING_ID,
        TEAM_WORKSPACE_ID,
        SPRINT_FOLDER_ID,
        "Design sync",
        datetime(2026, 10, 2, 14, 0, tzinfo=UTC),
        ProcessingState.QUEUED,
        SourceType.UPLOAD,
    ),
    _meeting(
        SPRINT_12_MEETING_ID,
        TEAM_WORKSPACE_ID,
        SPRINT_FOLDER_ID,
        "Sprint 12 review",
        datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
        ProcessingState.PROCESSED,
        SourceType.EXTENSION,
    ),
    _meeting(
        SPRINT_11_MEETING_ID,
        TEAM_WORKSPACE_ID,
        SPRINT_FOLDER_ID,
        "Sprint 11 review",
        datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        ProcessingState.PROCESSED,
        SourceType.EXTENSION,
    ),
    _meeting(
        UUID("6e5d4c3b-2a19-4807-96f5-e4d3c2b1a090"),
        PERSONAL_WORKSPACE_ID,
        PERSONAL_FOLDER_ID,
        "Thesis consultation",
        datetime(2026, 9, 25, 16, 30, tzinfo=UTC),
        ProcessingState.PROCESSED,
        SourceType.UPLOAD,
    ),
)
MEETINGS: Final = {meeting.id: meeting for meeting in _MEETINGS}

_ORIGINAL_REVISION_ID: Final = UUID("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
_ALICE_SPEAKER: Final = UUID("b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e")
_SECOND_SPEAKER: Final = UUID("c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f")

_TRANSCRIPT: Final = TranscriptRead(
    meeting_id=SPRINT_12_MEETING_ID,
    language="uk",
    model_name="parakeet-tdt-0.6b-v3",
    revision=RevisionRead(
        id=_ORIGINAL_REVISION_ID,
        revision_type=RevisionType.ORIGINAL,
        created_at=datetime(2026, 9, 30, 11, 2, tzinfo=UTC),
        edited_by_user_id=None,
        is_current=True,
    ),
    original_revision_id=_ORIGINAL_REVISION_ID,
    is_edited=False,
    has_unnamed_speakers=True,
    speakers=[
        SpeakerRead(id=_ALICE_SPEAKER, display_name="Alice", is_unnamed=False),
        SpeakerRead(id=_SECOND_SPEAKER, display_name="Speaker 2", is_unnamed=True),
    ],
    segments=[
        SegmentRead(
            id=UUID("d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80"),
            speaker_id=_ALICE_SPEAKER,
            start_seconds=0.0,
            end_seconds=6.2,
            text="Добрий день, починаємо sprint review. Спершу демо нового upload.",
        ),
        SegmentRead(
            id=UUID("e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091"),
            speaker_id=_SECOND_SPEAKER,
            start_seconds=6.8,
            end_seconds=14.5,
            text="Upload працює, але великі файли ще треба перевірити на staging.",
        ),
        SegmentRead(
            id=UUID("f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8091a2"),
            speaker_id=_ALICE_SPEAKER,
            start_seconds=15.1,
            end_seconds=20.4,
            text="Добре, додамо це в action items на наступний sprint.",
        ),
    ],
)
_NOTES: Final = NoteRead(
    id=UUID("0f1e2d3c-4b5a-4968-8776-655443322110"),
    preset=Preset.DETAILED,
    provider=Provider.WHADIO,
    model_name="gemma-3-12b-it",
    content="## Summary\nThe team demoed recording upload.\n\n"
    "## Action items\n- Test large uploads on staging (Speaker 2)",
    created_at=datetime(2026, 9, 30, 11, 4, tzinfo=UTC),
    created_by_user_id=None,
    is_current=True,
    context_meetings=[ContextMeetingRead(meeting_id=SPRINT_11_MEETING_ID, name="Sprint 11 review")],
)


def meeting(meeting_id: UUID) -> MeetingRead:
    if meeting_id not in MEETINGS:
        raise not_found("Meeting")
    return MEETINGS[meeting_id]


def transcribed(meeting_id: UUID) -> MeetingRead:
    found = meeting(meeting_id)
    if found.processing_state is not ProcessingState.PROCESSED:
        raise ApiError(409, ErrorCode.NOT_TRANSCRIBED, "The meeting has no transcript yet")
    return found


# Every processed stub meeting answers with the same transcript and notes.
def transcript(meeting_id: UUID) -> TranscriptRead:
    return _TRANSCRIPT.model_copy(update={"meeting_id": transcribed(meeting_id).id})


def notes(meeting_id: UUID) -> list[NoteRead]:
    found = meeting(meeting_id)
    return [_NOTES] if found.processing_state is ProcessingState.PROCESSED else []


async def seed_demo_meetings(db: AsyncSession) -> None:
    """Puts the demo folders and meetings above into the database, unless they are there."""
    if await db.get(Folder, PERSONAL_FOLDER_ID) is not None:
        return
    created_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    db.add_all(
        [
            Folder(
                folder_id=PERSONAL_FOLDER_ID,
                workspace_id=PERSONAL_WORKSPACE_ID,
                name="Default",
                created_at=created_at,
                is_default=True,
            ),
            Folder(
                folder_id=TEAM_DEFAULT_FOLDER_ID,
                workspace_id=TEAM_WORKSPACE_ID,
                name="Default",
                created_at=created_at,
                is_default=True,
            ),
            Folder(
                folder_id=SPRINT_FOLDER_ID,
                workspace_id=TEAM_WORKSPACE_ID,
                name="Sprint reviews",
                created_at=created_at,
                is_default=False,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            Meeting(
                meeting_id=item.id,
                folder_id=item.folder_id,
                created_by_user_id=item.created_by_user_id,
                name=item.name,
                name_is_generated=item.name_is_generated,
                source_type=item.source_type,
                recording_status=item.recording_status,
                processing_state=item.processing_state,
                storage_path=None,
                duration_seconds=item.duration_seconds,
                recorded_at=item.recorded_at,
                created_at=item.created_at,
                consent_confirmed_at=item.consent_confirmed_at,
                consent_confirmed_by_user_id=(
                    item.created_by_user_id if item.consent_confirmed_at else None
                ),
                recording_delete_after=item.recording_delete_after,
                recording_deleted_at=None,
                access_mode=item.access_mode,
            )
            for item in _MEETINGS
        ]
    )
    await db.commit()
