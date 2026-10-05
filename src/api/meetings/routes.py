from datetime import UTC, datetime
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile

from ..accounts.auth import BrowserUser, CaptureUser
from ..accounts.fixtures import workspace
from ..accounts.schemas import Provider, WorkspaceId
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    error_responses,
)
from ..core.schemas import Page, PageQuery, paginate
from .audio import SNIFF_BYTES, SUPPORTED_FORMATS, is_supported_audio
from .fixtures import (
    RETENTION,
    folder_in,
    meeting,
    meetings_of,
    notes,
    transcribed,
    transcript,
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
    SourceType,
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
) -> Page[MeetingSummary]:
    matching: list[MeetingSummary] = [
        item
        for item in meetings_of(workspace_id)
        if (query.folder_id is None or item.folder_id == query.folder_id)
        and (query.name is None or query.name.casefold() in item.name.casefold())
        and (query.recorded_from is None or item.recorded_at >= query.recorded_from)
        and (query.recorded_to is None or item.recorded_at < query.recorded_to)
    ]
    return paginate(matching, query)


@router.post(
    "/workspaces/{workspace_id}/meetings",
    status_code=201,
    tags=["meetings"],
    summary="Upload a recording",
    description=(
        "Any member. Multipart with the audio `file`, an optional `folder_id` and "
        f"`name`. Supported formats: {SUPPORTED_FORMATS}, recognised by the file's content "
        "whatever its name or declared type; any other file is refused and creates no "
        "meeting. Without `name`, the meeting is named after its date and time until it is "
        "renamed. The meeting is queued for processing at once; its speakers will be "
        "labelled `Speaker 1`, `Speaker 2` and so on."
    ),
    response_description="The new meeting, queued for processing",
    responses={
        201: {"headers": {"Location": {"description": "URL of the meeting"}}},
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
    folder_id: Annotated[
        UUID | None, Form(description="Destination folder; the default folder when omitted")
    ] = None,
    name: Annotated[MeetingName | None, Form(description="Meeting name")] = None,
) -> MeetingRead:
    workspace(workspace_id)
    target_folder_id = folder_in(workspace_id, folder_id)
    head = await file.read(SNIFF_BYTES)
    await file.seek(0)
    if not is_supported_audio(head):
        raise ApiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"The file is not a supported audio format: {SUPPORTED_FORMATS}",
        )
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise ApiError(413, ErrorCode.PAYLOAD_TOO_LARGE, "The file is larger than 500 MiB")
    now = datetime.now(UTC)
    created = MeetingRead(
        id=uuid4(),
        workspace_id=workspace_id,
        folder_id=target_folder_id,
        name=name or f"Meeting {now:%Y-%m-%d %H:%M} UTC",
        name_is_generated=name is None,
        recorded_at=now,
        processing_state=ProcessingState.QUEUED,
        recording_status=RecordingStatus.COMPLETE,
        source_type=SourceType.UPLOAD,
        duration_seconds=None,
        access_mode=AccessMode.WORKSPACE,
        created_by_user_id=user.id,
        created_at=now,
        failure_reason=None,
        is_edited=False,
        recording_available=True,
        recording_delete_after=now + RETENTION,
        consent_confirmed_at=None,
    )
    response.headers["Location"] = str(request.url_for("get_meeting", meeting_id=created.id))
    return created


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
async def get_meeting(meeting_id: MeetingId, user: BrowserUser) -> MeetingRead:
    return meeting(meeting_id)


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
    meeting_id: MeetingId, payload: MeetingUpdate, user: BrowserUser
) -> MeetingRead:
    target = meeting(meeting_id)
    if payload.folder_id is not None:
        folder_in(target.workspace_id, payload.folder_id)
    changes = payload.model_dump(exclude_none=True)
    if payload.name is not None:
        changes["name_is_generated"] = False
    return target.model_copy(update=changes)


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
async def delete_meeting(meeting_id: MeetingId, user: BrowserUser) -> None:
    meeting(meeting_id)


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
async def get_transcript(meeting_id: MeetingId, user: BrowserUser) -> TranscriptRead:
    return transcript(meeting_id)


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
    meeting_id: MeetingId, query: Annotated[PageQuery, Query()], user: BrowserUser
) -> Page[NoteRead]:
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
        202: {"headers": {"Location": {"description": "URL of the meeting to poll"}}},
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
) -> ProcessingJobRead:
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
