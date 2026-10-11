from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from ...export.services import ExportService
from ..accounts.auth import BrowserUser
from ..composition import Meetings
from ..core.errors import ApiError, ErrorCode, error_responses

router = APIRouter(
    tags=["export"],
    responses=error_responses(
        {
            401: "Authentication required",
            404: "Not found or not visible",
            409: "Content unavailable",
        }
    ),
)


class TranscriptFormat(StrEnum):
    MARKDOWN = "markdown"
    VTT = "vtt"


@router.get("/meetings/{meeting_id}/transcript/export")
async def export_transcript(
    meeting_id: UUID,
    user: BrowserUser,
    meetings: Meetings,
    *,
    export_format: Annotated[
        TranscriptFormat, Query(alias="format", description="Attachment format")
    ] = TranscriptFormat.MARKDOWN,
    timestamps: Annotated[bool, Query(description="Include timestamps in Markdown")] = True,
) -> Response:
    service = ExportService(meetings)
    if export_format == TranscriptFormat.VTT:
        return Response(
            await service.transcript_vtt(user.id, meeting_id),
            media_type="text/vtt",
            headers={"Content-Disposition": 'attachment; filename="transcript.vtt"'},
        )
    return Response(
        await service.transcript_markdown(user.id, meeting_id, timestamps=timestamps),
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="transcript.md"'},
    )


@router.get("/meetings/{meeting_id}/notes/export")
async def export_notes(meeting_id: UUID, user: BrowserUser, meetings: Meetings) -> Response:
    content = await ExportService(meetings).notes_markdown(user.id, meeting_id)
    if content is None:
        raise ApiError(409, ErrorCode.NO_NOTES, "No notes yet")
    return Response(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="notes.md"'},
    )
