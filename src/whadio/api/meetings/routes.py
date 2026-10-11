import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import Field

from ...accounts.enums import NotesTemplate
from ...meetings.enums import MeetingSource
from ...meetings.services import RecordingInput
from ...shared.errors import Failure, UseCaseError
from ...shared.pagination import ListCursor
from ..accounts.auth import BrowserUser, CaptureUser
from ..accounts.schemas import Preset, Provider, WorkspaceId
from ..composition import Meetings, Persistence, Processing, Recordings, UploadGuard
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    error_responses,
)
from ..core.pagination import list_page, list_window
from ..core.schemas import Output, Page, PageQuery
from .audio import SUPPORTED_FORMATS, is_supported_audio
from .pagination import meeting_filter, meeting_page
from .schemas import (
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
    TranscriptRead,
)
from .upload_limits import MAX_UPLOAD_BYTES, RecordingUploadRoute
from .views import meeting_read, meeting_summary, notes_read, transcript_read

router = APIRouter(route_class=RecordingUploadRoute)


async def _validate_upload(file: UploadFile) -> None:
    size = await asyncio.to_thread(file.file.seek, 0, 2)
    await file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise ApiError(413, ErrorCode.PAYLOAD_TOO_LARGE, "The recording exceeds 500 MiB")
    if not await asyncio.to_thread(is_supported_audio, file.file):
        raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "The file is not supported audio")
    await file.seek(0)


_WORKSPACE_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"
_MEETING_NOT_FOUND = (
    "`NOT_FOUND`: no such meeting, or the caller cannot read it (restricted meetings are "
    "reported as missing, never as forbidden)"
)
_NOT_TRANSCRIBED = f"`{ErrorCode.NOT_TRANSCRIBED}`: the meeting is not processed yet"

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
    service: Meetings,
) -> Page[MeetingSummary]:
    matching = [
        meeting_summary(item, workspace_id)
        for item in await service.list_meetings(
            user.id,
            meeting_filter(workspace_id, query),
        )
    ]
    return meeting_page(matching, query.limit)


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
                400: "`MALFORMED_REQUEST`: invalid or repeated Content-Length header",
                401: DOC_UNAUTHENTICATED,
                404: _WORKSPACE_NOT_FOUND,
                413: f"`{ErrorCode.PAYLOAD_TOO_LARGE}`: the file is larger than 500 MiB "
                "or the multipart request exceeds 501 MiB",
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
    service: Meetings,
    persistence: Persistence,
    processing: Processing,
    recordings: Recordings,
    upload_guard: UploadGuard,
    response: Response,
    folder_id: Annotated[
        UUID | None, Form(description="Destination folder; the default folder when omitted")
    ] = None,
    name: Annotated[MeetingName | None, Form(description="Meeting name")] = None,
) -> MeetingRead:
    folders = await service.folders(user.id, workspace_id)
    if folder_id is not None and folder_id not in {item.folder_id for item in folders}:
        raise UseCaseError(Failure.VALIDATION_ERROR)
    if name is not None and not name.strip():
        raise UseCaseError(Failure.VALIDATION_ERROR)
    try:
        await _validate_upload(file)
        now = datetime.now(UTC)
        key = f"recordings/{uuid4()}"
        await upload_guard.reserve(key)
        await recordings.put(key, file.file)
        meeting = await persistence.ingest(
            user.id,
            workspace_id,
            RecordingInput(key, now, MeetingSource.UPLOAD, name=name, folder_id=folder_id),
            now,
        )
        await processing.queue_transcription(meeting.meeting_id)
        response.headers["Location"] = f"/api/v1/meetings/{meeting.meeting_id}"
        await upload_guard.release(key)
        return meeting_read(meeting, workspace_id, is_edited=False)
    except BaseException:
        await asyncio.shield(recordings.rollback())
        raise
    finally:
        await file.close()


class PlaybackLink(Output):
    url: str = Field(description="Authorized playback link, valid for five minutes.")
    expires_at: datetime = Field(description="When the playback link expires.")


@router.get(
    "/meetings/{meeting_id}/recording",
    tags=["meetings"],
    summary="Get a recording playback link",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            404: _MEETING_NOT_FOUND,
            409: "`RECORDING_NOT_READY`: recording is still being captured",
            410: "`RECORDING_DELETED`: retention removed the recording",
        }
    ),
    description=(
        "Get a five-minute playback link after checking meeting access. Refuses "
        "unfinished recordings and recordings removed by retention."
    ),
)
async def recording_link(
    meeting_id: MeetingId,
    user: BrowserUser,
    service: Meetings,
    recordings: Recordings,
) -> PlaybackLink:
    link = await recordings.playback(service, user.id, meeting_id)
    return PlaybackLink(url=link.url, expires_at=link.expires_at)


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
async def get_meeting(meeting_id: MeetingId, user: BrowserUser, service: Meetings) -> MeetingRead:
    target = await service.get(user.id, meeting_id)
    workspace_id = await service.workspace_id(user.id, meeting_id)
    try:
        version = await service.transcript(user.id, meeting_id)
    except UseCaseError as error:
        if error.code != Failure.NOT_TRANSCRIBED:
            raise
        is_edited = False
    else:
        is_edited = version.is_edited
    return meeting_read(target, workspace_id, is_edited=is_edited)


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
    meeting_id: MeetingId, payload: MeetingUpdate, user: BrowserUser, service: Meetings
) -> MeetingRead:
    await service.update(
        user.id, meeting_id, datetime.now(UTC), name=payload.name, folder_id=payload.folder_id
    )
    return await get_meeting(meeting_id, user, service)


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
async def delete_meeting(meeting_id: MeetingId, user: BrowserUser, service: Meetings) -> None:
    await service.delete(user.id, meeting_id, datetime.now(UTC))


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
async def get_transcript(
    meeting_id: MeetingId,
    user: BrowserUser,
    service: Meetings,
    revision_id: Annotated[
        UUID | None, Query(description="Revision to read; current when omitted")
    ] = None,
) -> TranscriptRead:
    return transcript_read(await service.transcript(user.id, meeting_id, revision_id))


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
    meeting_id: MeetingId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    service: Meetings,
) -> Page[NoteRead]:
    scope = f"notes:{meeting_id}:{user.id}"
    versions = await service.notes(
        user.id, meeting_id, list_window(query, scope, chronological=True)
    )
    last = versions[min(len(versions), query.limit) - 1].note if versions else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.note_id)
    return list_page(notes_read(versions), query, scope, cursor)


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
    processing: Processing,
    service: Meetings,
    response: Response,
) -> ProcessingJobRead:
    await service.get(user.id, meeting_id)
    job = await processing.queue_notes(
        meeting_id,
        user.id,
        None if payload.preset is None else NotesTemplate(payload.preset.value),
        use_builtin_model=payload.use_builtin_model,
        now=datetime.now(UTC),
    )
    response.headers["Location"] = f"/api/v1/meetings/{meeting_id}"
    return ProcessingJobRead(
        id=job.job_id,
        meeting_id=job.meeting_id,
        kind=JobKind.NOTES,
        status=JobStatus.QUEUED,
        preset=Preset(job.preset.value),
        provider=Provider(job.provider.value.lower()),
        created_at=job.created_at,
    )
