from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from ...capture.services import (
    MAX_CHUNK_BYTES,
    CaptureView,
    ChunkUpload,
    MissingChunksError,
    SpeakerEvent,
)
from ...shared.errors import Failure, UseCaseError
from ..accounts.auth import CaptureUser
from ..composition import Captures
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
)
from ..core.schemas import Page, PageQuery, paginate
from .schemas import (
    CaptureComplete,
    CaptureCreate,
    CaptureId,
    CaptureRead,
    CaptureStatus,
    ChunkSeq,
    DestinationRead,
    FolderOption,
    SpeakerEventInput,
)

router = APIRouter(tags=["capture"])

_SPEAKER_EVENTS: Final = TypeAdapter(list[SpeakerEventInput])
_NOT_FOUND = "`NOT_FOUND`: no such capture, or another account opened it"
_CLOSED = f"`{ErrorCode.CAPTURE_CLOSED}`: the capture was completed or finalised"


def _capture_read(view: CaptureView) -> CaptureRead:
    return CaptureRead(
        id=view.capture_id,
        meeting_id=view.meeting_id,
        status=CaptureStatus(view.status.value),
        received_seqs=list(view.received_seqs),
        max_chunk_bytes=MAX_CHUNK_BYTES,
    )


@router.get(
    "/captures/destinations",
    summary="Where a recording can go",
    description="The caller's workspaces, oldest first, each with the folders a recording can "
    "be filed in. The folder is the notes context, so it is chosen before recording.",
    response_description="A page of workspaces with their folders",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def list_destinations(
    query: Annotated[PageQuery, Query()], user: CaptureUser, captures: Captures
) -> Page[DestinationRead]:
    found: list[DestinationRead] = [
        DestinationRead(
            workspace_id=item.workspace.workspace_id,
            name=item.workspace.name,
            is_personal=item.workspace.is_personal,
            folders=[
                FolderOption(id=folder.folder_id, name=folder.name, is_default=folder.is_default)
                for folder in item.folders
            ],
        )
        for item in await captures.destinations(user.id)
    ]
    return paginate(found, query)


@router.post(
    "/captures",
    status_code=201,
    summary="Start recording",
    description="Opens a capture and creates its meeting in state `recording`. "
    "`consent_confirmed` must be `true`, and the confirmation is stored with the meeting. "
    "Without a destination the meeting goes to the default folder of the caller's personal "
    "workspace.",
    response_description="The open capture",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: DOC_UNAUTHENTICATED,
            404: "`NOT_FOUND`: no such workspace, or the caller is not a member",
            422: f"{DOC_INVALID}; `consent_confirmed` must be `true`, and `folder_id` must be "
            "a folder of the workspace",
        }
    ),
)
async def start_capture(
    payload: CaptureCreate, user: CaptureUser, captures: Captures, response: Response
) -> CaptureRead:
    view = await captures.start(
        user.id,
        payload.workspace_id,
        payload.folder_id,
        consent_confirmed=payload.consent_confirmed,
        now=datetime.now(UTC),
    )
    response.headers["Location"] = f"/api/v1/captures/{view.capture_id}"
    return _capture_read(view)


@router.get(
    "/captures/{capture_id}",
    summary="Get a capture",
    description="The capture with the numbers of the chunks already stored, so the extension "
    "can resume after a lost connection and upload only what is missing.",
    response_description="The capture",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 404: _NOT_FOUND, 422: DOC_INVALID}),
)
async def get_capture(capture_id: CaptureId, user: CaptureUser, captures: Captures) -> CaptureRead:
    return _capture_read(await captures.get(user.id, capture_id))


@router.put(
    "/captures/{capture_id}/chunks/{seq}",
    status_code=201,
    summary="Upload one chunk",
    description="Multipart with the `audio` part (`audio/*`) and `speaker_events`, a JSON list "
    "of the participants seen speaking during the chunk. Uploading the same chunk again "
    "changes nothing.",
    response_description="The chunk was stored",
    responses={
        200: {"description": "The same chunk was already stored"},
        **error_responses(
            {
                401: DOC_UNAUTHENTICATED,
                404: _NOT_FOUND,
                409: f"`{ErrorCode.CHUNK_MISMATCH}`: different audio is already stored under "
                f"this number; {_CLOSED}",
                413: f"`{ErrorCode.PAYLOAD_TOO_LARGE}`: the chunk exceeds `max_chunk_bytes`",
                415: f"`{ErrorCode.UNSUPPORTED_MEDIA_TYPE}`: the part is not `audio/*`",
                422: f"{DOC_INVALID}; the chunk is empty or `speaker_events` is invalid",
            }
        ),
    },
)
async def put_chunk(
    capture_id: CaptureId,
    seq: ChunkSeq,
    audio: Annotated[UploadFile, File(description="The chunk's audio, `audio/*`")],
    user: CaptureUser,
    captures: Captures,
    response: Response,
    speaker_events: Annotated[
        str,
        Form(
            max_length=200_000,
            description="JSON list of `{at_seconds, speakers}` seen during the chunk",
        ),
    ] = "[]",
) -> None:
    try:
        if not (audio.content_type or "").startswith("audio/"):
            raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "The chunk is not audio")
        data = await audio.read(MAX_CHUNK_BYTES + 1)
    finally:
        await audio.close()
    if len(data) > MAX_CHUNK_BYTES:
        raise ApiError(
            413, ErrorCode.PAYLOAD_TOO_LARGE, f"A chunk is at most {MAX_CHUNK_BYTES} bytes"
        )
    try:
        events = _SPEAKER_EVENTS.validate_json(speaker_events)
    except ValidationError:
        raise UseCaseError(Failure.VALIDATION_ERROR) from None
    created = await captures.put_chunk(
        user.id,
        capture_id,
        ChunkUpload(
            seq,
            data,
            tuple(SpeakerEvent(event.at_seconds, tuple(event.speakers)) for event in events),
        ),
        datetime.now(UTC),
    )
    if not created:
        response.status_code = 200


@router.post(
    "/captures/{capture_id}/complete",
    summary="Finish recording",
    description="Joins chunks `0..last_seq` into the recording and queues the meeting through "
    "the same path as an upload. Repeating it with the same `last_seq` returns the same "
    "result.",
    response_description="The assembled capture",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: DOC_UNAUTHENTICATED,
            404: _NOT_FOUND,
            409: f"`{ErrorCode.MISSING_CHUNKS}`: numbers below `last_seq` never arrived, "
            f"listed in `details`; `{ErrorCode.EMPTY_CAPTURE}`: no chunk arrived; "
            f"`{ErrorCode.CAPTURE_CLOSED}`: already finalised with a different `last_seq`",
            422: DOC_INVALID,
            503: f"`{ErrorCode.INTEGRATION_UNAVAILABLE}`: storage or the job queue is unavailable",
        }
    ),
)
async def complete_capture(
    capture_id: CaptureId, payload: CaptureComplete, user: CaptureUser, captures: Captures
) -> CaptureRead:
    try:
        view = await captures.complete(user.id, capture_id, payload.last_seq, datetime.now(UTC))
    except MissingChunksError as error:
        raise ApiError(
            409,
            ErrorCode.MISSING_CHUNKS,
            "Some chunks never arrived",
            [
                ErrorDetail(field="last_seq", message=f"chunk {seq} is missing")
                for seq in error.missing
            ],
        ) from None
    return _capture_read(view)
