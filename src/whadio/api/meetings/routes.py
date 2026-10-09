import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ..accounts.auth import BrowserUser, CaptureUser
from ..accounts.fixtures import workspace
from ..accounts.models import WorkspaceMembership
from ..accounts.schemas import Provider, Role, UserRead, WorkspaceId
from ..audit.models import AuditAction, AuditEvent
from ..core.db import Db
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
    not_found,
)
from ..core.schemas import Page, PageQuery, paginate
from .audio import SUPPORTED_FORMATS, is_supported_audio
from .fixtures import (
    RETENTION,
    notes,
    transcribed,
)
from .models import (
    Folder,
    Meeting,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)
from .schemas import (
    AccessMode,
    JobKind,
    JobStatus,
    MeetingId,
    MeetingListQuery,
    MeetingName,
    MeetingRead,
    MeetingSummary,
    MeetingUpdate,
    NoteRead,
    NotesRequest,
    ProcessingJobRead,
    ProcessingState,
    RecordingStatus,
    RevisionRead,
    RevisionType,
    SegmentRead,
    SourceType,
    SpeakerRead,
    TranscriptRead,
)

router = APIRouter()

MAX_UPLOAD_BYTES: Final = 500 * 1024 * 1024

_WORKSPACE_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"
_MEETING_NOT_FOUND = (
    "`NOT_FOUND`: no such meeting, or the caller cannot read it (restricted meetings are "
    "reported as missing, never as forbidden)"
)
_NOT_TRANSCRIBED = f"`{ErrorCode.NOT_TRANSCRIBED}`: the meeting is not processed yet"


async def _check_can_read(db: Db, meeting_id: UUID, user: UserRead) -> None:
    """404 unless the meeting exists and the caller is a member of its workspace.

    Restricted meetings are not checked yet: that rule arrives with Access Policy.
    """
    readable = await db.scalar(
        select(Meeting.meeting_id)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Folder.workspace_id)
        .where(Meeting.meeting_id == meeting_id, WorkspaceMembership.user_id == user.id)
    )
    if readable is None:
        raise not_found("Meeting")


# --- Meetings ---


@router.get(
    "/workspaces/{workspace_id}/meetings",
    tags=["meetings"],
    summary="List meetings",
    description="Meetings the caller can read, newest recording first, with their processing "
    "state. Restricted meetings the caller was not selected for are left out. "
    "Filters combine; an empty page means nothing matched.",
    response_description="A page of meetings",
    responses=error_responses(
        {401: DOC_UNAUTHENTICATED, 404: _WORKSPACE_NOT_FOUND, 422: DOC_INVALID}
    ),
)
async def list_meetings(
    workspace_id: WorkspaceId,
    query: Annotated[MeetingListQuery, Query()],
    user: BrowserUser,
    db: Db,
) -> Page[MeetingSummary]:
    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise not_found("Workspace")
    # Every meeting is workspace-wide for now: restricted ones arrive with Access Policy.
    statement = (
        select(Meeting)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .where(Folder.workspace_id == workspace_id)
        .order_by(Meeting.recorded_at.desc(), Meeting.meeting_id)
    )
    if query.folder_id is not None:
        statement = statement.where(Meeting.folder_id == query.folder_id)
    if query.name is not None:
        statement = statement.where(Meeting.name.icontains(query.name, autoescape=True))
    if query.recorded_from is not None:
        statement = statement.where(Meeting.recorded_at >= query.recorded_from)
    if query.recorded_to is not None:
        statement = statement.where(Meeting.recorded_at < query.recorded_to)
    matching: list[MeetingSummary] = [
        MeetingSummary(
            id=item.meeting_id,
            workspace_id=workspace_id,
            folder_id=item.folder_id,
            name=item.name,
            name_is_generated=item.name_is_generated,
            recorded_at=item.recorded_at,
            processing_state=item.processing_state,
            recording_status=item.recording_status,
            source_type=item.source_type,
            duration_seconds=item.duration_seconds,
            access_mode=item.access_mode,
        )
        for item in await db.scalars(statement)
    ]
    return paginate(matching, query)


@router.post(
    "/workspaces/{workspace_id}/meetings",
    status_code=201,
    tags=["meetings"],
    summary="Upload a recording",
    description=(
        "Any member. Multipart with the audio `file`, an optional `folder_id` and "
        f"`name`. Supported formats: {SUPPORTED_FORMATS}. The server decodes the file to "
        "check, whatever its name or declared type; any other file is refused and creates no "
        "meeting. Without `name`, the meeting is named after its date and time until it is "
        "renamed. The meeting is queued for processing at once; its speakers will be "
        "labelled `Speaker 1`, `Speaker 2` and so on."
    ),
    response_description="The new meeting, queued for processing",
    responses={
        201: {
            "headers": {
                "Location": {
                    "description": "URL of the meeting",
                    "schema": {"type": "string", "format": "uri"},
                }
            }
        },
        **error_responses(
            {
                401: DOC_UNAUTHENTICATED,
                404: _WORKSPACE_NOT_FOUND,
                413: f"`{ErrorCode.PAYLOAD_TOO_LARGE}`: the file is larger than 500 MiB",
                415: f"`{ErrorCode.UNSUPPORTED_MEDIA_TYPE}`: the content is not a supported "
                "audio format",
                422: f"{DOC_INVALID}; `folder_id` must be a folder of this workspace",
            }
        ),
    },
)
async def upload_recording(
    workspace_id: WorkspaceId,
    file: Annotated[UploadFile, File(description=f"The recording: {SUPPORTED_FORMATS}")],
    user: CaptureUser,
    request: Request,
    response: Response,
    db: Db,
    folder_id: Annotated[
        UUID | None, Form(description="Destination folder; the default folder when omitted")
    ] = None,
    name: Annotated[MeetingName | None, Form(description="Meeting name")] = None,
) -> MeetingRead:
    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise not_found("Workspace")
    if folder_id is None:
        folder = await db.scalar(
            select(Folder).where(Folder.workspace_id == workspace_id, Folder.is_default)
        )
    else:
        folder = await db.scalar(
            select(Folder).where(Folder.workspace_id == workspace_id, Folder.folder_id == folder_id)
        )
    if folder is None:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request contains invalid fields",
            [
                ErrorDetail(
                    field="folder_id",
                    message="is not a folder of this workspace",
                    provided_value=str(folder_id),
                )
            ],
        )
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise ApiError(413, ErrorCode.PAYLOAD_TOO_LARGE, "The file is larger than 500 MiB")

    is_audio = await run_in_threadpool(is_supported_audio, file.file)
    if not is_audio:
        raise ApiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"The file is not a supported audio format: {SUPPORTED_FORMATS}",
        )

    await file.seek(0)

    # 1. Save the recording, 2. the meeting row, 3. the job (not yet: no queue), 4. respond.
    meeting_id = uuid4()
    recordings_dir: Path = request.app.state.recordings_dir
    await run_in_threadpool(recordings_dir.mkdir, parents=True, exist_ok=True)
    storage_path = recordings_dir / str(meeting_id)
    with storage_path.open("wb") as saved:
        await run_in_threadpool(shutil.copyfileobj, file.file, saved)

    now = datetime.now(UTC)
    created = Meeting(
        meeting_id=meeting_id,
        folder_id=folder.folder_id,
        created_by_user_id=user.id,
        name=name or f"Meeting {now:%Y-%m-%d %H:%M} UTC",
        name_is_generated=name is None,
        source_type=SourceType.UPLOAD,
        recording_status=RecordingStatus.COMPLETE,
        processing_state=ProcessingState.QUEUED,
        storage_path=str(storage_path),
        duration_seconds=None,
        recorded_at=now,
        created_at=now,
        consent_confirmed_at=None,
        consent_confirmed_by_user_id=None,
        recording_delete_after=now + RETENTION,
        recording_deleted_at=None,
        access_mode=AccessMode.WORKSPACE,
    )
    db.add(created)
    await db.commit()

    response.headers["Location"] = str(request.url_for("get_meeting", meeting_id=meeting_id))
    return MeetingRead(
        id=meeting_id,
        workspace_id=workspace_id,
        folder_id=created.folder_id,
        name=created.name,
        name_is_generated=created.name_is_generated,
        recorded_at=now,
        processing_state=created.processing_state,
        recording_status=created.recording_status,
        source_type=created.source_type,
        duration_seconds=None,
        access_mode=created.access_mode,
        created_by_user_id=user.id,
        created_at=now,
        failure_reason=None,
        is_edited=False,
        recording_available=True,
        recording_delete_after=created.recording_delete_after,
        consent_confirmed_at=None,
    )


@router.get(
    "/meetings/{meeting_id}",
    tags=["meetings"],
    summary="Get a meeting",
    description="Poll this while `processing_state` is `recording`, `queued` or `processing`.",
    response_description="The meeting",
    responses=error_responses(
        {401: DOC_UNAUTHENTICATED, 404: _MEETING_NOT_FOUND, 422: DOC_INVALID}
    ),
)
async def get_meeting(meeting_id: MeetingId, user: BrowserUser, db: Db) -> MeetingRead:
    # Meeting + its folder's workspace_id (MeetingRead needs it, the row doesn't have it)
    row = await db.execute(
        select(Meeting, Folder.workspace_id)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Folder.workspace_id)
        .where(Meeting.meeting_id == meeting_id, WorkspaceMembership.user_id == user.id)
    )
    # None both for a missing meeting and for one the caller cannot read: same 404 either way.
    pair = row.one_or_none()
    if pair is None:
        raise not_found("Meeting")
    found, workspace_id = pair

    return MeetingRead.model_validate(
        {
            # copy every field with the same name on both: name, folder_id, recorded_at, ...
            **{
                name: getattr(found, name)
                for name in MeetingRead.model_fields
                if hasattr(found, name)
            },
            # the 5 the row can't give
            "id": found.meeting_id,
            "workspace_id": workspace_id,
            "failure_reason": None,  # no processing jobs table yet
            "is_edited": False,  # no transcripts yet
            "recording_available": found.storage_path is not None
            and found.recording_deleted_at is None,
        }
    )


@router.patch(
    "/meetings/{meeting_id}",
    tags=["meetings"],
    summary="Rename or move a meeting",
    description="Any member who can read the meeting. Renaming clears `name_is_generated`. "
    "Moving keeps the recording, transcript and notes; only folders of the same workspace "
    "are accepted, and later notes use the new folder as context. `recorded_at` "
    "cannot be changed.",
    response_description="The updated meeting",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: DOC_UNAUTHENTICATED,
            404: _MEETING_NOT_FOUND,
            422: f"{DOC_INVALID}; `folder_id` must be a folder of the meeting's workspace",
        }
    ),
)
async def update_meeting(
    meeting_id: MeetingId, payload: MeetingUpdate, user: BrowserUser, db: Db
) -> MeetingRead:
    row = await db.execute(
        select(Meeting, Folder.workspace_id)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Folder.workspace_id)
        .where(Meeting.meeting_id == meeting_id, WorkspaceMembership.user_id == user.id)
    )
    found = row.one_or_none()
    if found is None:
        raise not_found("Meeting")
    target, workspace_id = found
    now = datetime.now(UTC)

    if payload.folder_id is not None and payload.folder_id != target.folder_id:
        folder = await db.scalar(
            select(Folder).where(
                Folder.folder_id == payload.folder_id, Folder.workspace_id == workspace_id
            )
        )
        if folder is None:
            raise ApiError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request contains invalid fields",
                [
                    ErrorDetail(
                        field="folder_id",
                        message="is not a folder of this workspace",
                        provided_value=str(payload.folder_id),
                    )
                ],
            )
        db.add(
            AuditEvent(
                occurred_at=now,
                actor_user_id=user.id,
                action=AuditAction.MEETING_MOVED,
                workspace_id=workspace_id,
                meeting_id=meeting_id,
                details={"from": str(target.folder_id), "to": str(folder.folder_id)},
            )
        )
        target.folder_id = folder.folder_id

    if payload.name is not None:
        if payload.name != target.name:
            db.add(
                AuditEvent(
                    occurred_at=now,
                    actor_user_id=user.id,
                    action=AuditAction.MEETING_RENAMED,
                    workspace_id=workspace_id,
                    meeting_id=meeting_id,
                )
            )
        target.name = payload.name
        target.name_is_generated = False

    await db.commit()
    return await get_meeting(meeting_id, user, db)


@router.delete(
    "/meetings/{meeting_id}",
    status_code=204,
    tags=["meetings"],
    summary="Delete a meeting",
    description="The member who recorded it, a Moderator or the Owner. Deletes the "
    "recording, transcript and notes; notes of other meetings that used it as context keep "
    "their text.",
    response_description="Deleted",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            403: f"`{ErrorCode.INSUFFICIENT_ROLE}`: neither its recorder nor a Moderator",
            404: _MEETING_NOT_FOUND,
            422: DOC_INVALID,
        }
    ),
)
async def delete_meeting(meeting_id: MeetingId, user: BrowserUser, db: Db) -> None:
    row = await db.execute(
        select(Meeting, Folder.workspace_id, WorkspaceMembership.role)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Folder.workspace_id)
        .where(Meeting.meeting_id == meeting_id, WorkspaceMembership.user_id == user.id)
    )
    found = row.one_or_none()
    if found is None:
        raise not_found("Meeting")
    target, workspace_id, role = found
    if role is Role.MEMBER and target.created_by_user_id != user.id:
        raise ApiError(
            403,
            ErrorCode.INSUFFICIENT_ROLE,
            "Only whoever recorded the meeting, a Moderator or the Owner can delete it",
        )

    # Transcripts and notes are not stored yet; once they are, they go here too.
    await db.delete(target)
    # Same transaction as the deletion (ADR-005); no foreign keys, so it outlives the meeting.
    db.add(
        AuditEvent(
            occurred_at=datetime.now(UTC),
            actor_user_id=user.id,
            action=AuditAction.MEETING_DELETED,
            workspace_id=workspace_id,
            meeting_id=meeting_id,
        )
    )
    await db.commit()
    # After the commit, so a failed commit never leaves a meeting without its recording.
    if target.storage_path is not None:
        await run_in_threadpool(Path(target.storage_path).unlink, missing_ok=True)


@router.get(
    "/meetings/{meeting_id}/transcript",
    tags=["meetings"],
    summary="Get the transcript",
    description="The current revision: timestamped segments with speaker labels. "
    "The original stays reachable through `original_revision_id`.",
    response_description="The current revision of the transcript",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            404: _MEETING_NOT_FOUND,
            409: _NOT_TRANSCRIBED,
            422: DOC_INVALID,
        }
    ),
)
async def get_transcript(meeting_id: MeetingId, user: BrowserUser, db: Db) -> TranscriptRead:
    await _check_can_read(db, meeting_id, user)
    found = await db.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))
    if found is None:
        raise ApiError(409, ErrorCode.NOT_TRANSCRIBED, "The meeting has no transcript yet")

    revisions = [
        *await db.scalars(
            select(TranscriptRevision).where(
                TranscriptRevision.transcript_id == found.transcript_id
            )
        )
    ]
    current = next(r for r in revisions if r.revision_id == found.current_revision_id)
    original = next(r for r in revisions if r.revision_type is RevisionType.ORIGINAL)
    speakers = [
        SpeakerRead(
            id=speaker.speaker_id,
            display_name=speaker.display_name,
            # Placeholders are the "Speaker 1", "Speaker 2", ... labels transcription gives.
            is_unnamed=re.fullmatch(r"Speaker \d+", speaker.display_name) is not None,
        )
        for speaker in await db.scalars(
            select(Speaker)
            .where(Speaker.revision_id == current.revision_id)
            .order_by(Speaker.display_name)
        )
    ]
    segments = [
        SegmentRead(
            id=segment.segment_id,
            speaker_id=segment.speaker_id,
            start_seconds=segment.start_time_seconds,
            end_seconds=segment.end_time_seconds,
            text=segment.text,
        )
        for segment in await db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.revision_id == current.revision_id)
            .order_by(TranscriptSegment.start_time_seconds)
        )
    ]
    return TranscriptRead(
        meeting_id=meeting_id,
        language=found.language,
        model_name=found.model_name,
        revision=RevisionRead(
            id=current.revision_id,
            revision_type=current.revision_type,
            created_at=current.created_at,
            edited_by_user_id=current.edited_by_user_id,
            is_current=True,
        ),
        original_revision_id=original.revision_id,
        is_edited=any(r.revision_type is RevisionType.EDITED for r in revisions),
        has_unnamed_speakers=any(speaker.is_unnamed for speaker in speakers),
        speakers=speakers,
        segments=segments,
    )


# --- Notes ---


@router.get(
    "/meetings/{meeting_id}/notes",
    tags=["notes"],
    summary="List the meeting's notes",
    description="Every generated version, newest first; the first one is current. Each lists "
    "the meetings used as context, so readers can see where statements came from.",
    response_description="A page of notes",
    responses=error_responses(
        {401: DOC_UNAUTHENTICATED, 404: _MEETING_NOT_FOUND, 422: DOC_INVALID}
    ),
)
async def list_notes(
    meeting_id: MeetingId, query: Annotated[PageQuery, Query()], user: BrowserUser, db: Db
) -> Page[NoteRead]:
    await _check_can_read(db, meeting_id, user)
    return paginate(notes(meeting_id), query)


@router.post(
    "/meetings/{meeting_id}/notes",
    status_code=202,
    tags=["notes"],
    summary="Regenerate the notes",
    description=(
        "Any member who can read the meeting. Queues notes generation with the chosen preset "
        "and answers at once with `202`: generation runs in a worker. Poll the meeting in "
        "`Location` until `processing_state` is `processed` or `failed`.\n\n"
        "Limits: one run at a time, and a configured number of regenerations per "
        "meeting (3 by default); every requested run counts, failed ones included. The "
        "transcript is never regenerated, and a failed run keeps the previous notes current."
    ),
    response_description="The queued job",
    responses={
        202: {
            "headers": {
                "Location": {
                    "description": "URL of the meeting to poll",
                    "schema": {"type": "string", "format": "uri"},
                }
            }
        },
        **error_responses(
            {
                400: DOC_MALFORMED,
                401: DOC_UNAUTHENTICATED,
                404: _MEETING_NOT_FOUND,
                409: f"`{ErrorCode.NOTES_IN_PROGRESS}`: a run is already queued or running; "
                f"`{ErrorCode.REGENERATION_LIMIT}`: the meeting used up its regenerations; "
                f"{_NOT_TRANSCRIBED}",
                422: DOC_INVALID,
            }
        ),
    },
)
async def regenerate_notes(
    meeting_id: MeetingId,
    payload: NotesRequest,
    user: BrowserUser,
    request: Request,
    response: Response,
    db: Db,
) -> ProcessingJobRead:
    await _check_can_read(db, meeting_id, user)
    target = transcribed(meeting_id)
    preset = payload.preset or workspace(target.workspace_id).default_preset
    provider = (
        Provider.WHADIO
        if payload.use_builtin_model
        else workspace(target.workspace_id).notes_provider
    )
    response.headers["Location"] = str(request.url_for("get_meeting", meeting_id=meeting_id))
    return ProcessingJobRead(
        id=uuid4(),
        meeting_id=meeting_id,
        kind=JobKind.NOTES,
        status=JobStatus.QUEUED,
        preset=preset,
        provider=provider,
        created_at=datetime.now(UTC),
    )
