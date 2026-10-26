from typing import Annotated

from fastapi import APIRouter, Query, Response

from ...export.services import ExportFormat, ExportVersion
from ..accounts.auth import BrowserUser
from ..composition import Exports
from ..core.errors import ApiError, ErrorCode, error_responses
from ..meetings.schemas import MeetingId

router = APIRouter(
    tags=["export"],
    responses=error_responses(
        {
            401: "Authentication required",
            404: "Not found or not visible",
            409: "Content unavailable",
            422: "Invalid export options",
        }
    ),
)


@router.get(
    "/meetings/{meeting_id}/transcript/export",
    summary="Download a transcript",
    description=(
        "Download the current or immutable original transcript as UTF-8 "
        "Markdown or WebVTT. Requires meeting membership/access; share grants "
        "and administrator status confer no export rights. Link headers and "
        "the file identify the original. VTT is always timed."
    ),
    responses={
        200: {
            "content": {
                "text/markdown": {"schema": {"type": "string"}},
                "text/vtt": {"schema": {"type": "string"}},
            },
            "headers": {
                "Link": {
                    "description": "Authenticated original view and download URLs",
                    "schema": {"type": "string"},
                }
            },
        }
    },
    response_class=Response,
)
async def export_transcript(
    meeting_id: MeetingId,
    user: BrowserUser,
    service: Exports,
    *,
    export_format: Annotated[
        ExportFormat, Query(alias="format", description="Attachment format")
    ] = ExportFormat.MARKDOWN,
    version: Annotated[
        ExportVersion, Query(description="Current revision or immutable original")
    ] = ExportVersion.CURRENT,
    timestamps: Annotated[
        bool, Query(description="Include timestamps in Markdown; VTT is always timed")
    ] = True,
) -> Response:
    document = await service.transcript(
        user.id, meeting_id, export_format, version, timestamps=timestamps
    )
    suffix = "vtt" if export_format == ExportFormat.VTT else "md"
    return Response(
        document.content,
        media_type="text/vtt" if suffix == "vtt" else "text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="transcript.{suffix}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Link": (
                f'<{document.original_view}>; rel="original", '
                f'<{document.original_download}>; rel="alternate"'
            ),
        },
    )


@router.get(
    "/meetings/{meeting_id}/notes/export",
    summary="Download current notes",
    description=(
        "Download the latest saved notes and context provenance as UTF-8 "
        "Markdown. Requires meeting access, not an external share. No notes "
        "returns 409 NO_NOTES."
    ),
    responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}},
    response_class=Response,
)
async def export_notes(meeting_id: MeetingId, user: BrowserUser, service: Exports) -> Response:
    content = await service.notes_markdown(user.id, meeting_id)
    if content is None:
        raise ApiError(409, ErrorCode.NO_NOTES, "No notes yet")
    return Response(
        content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": 'attachment; filename="notes.md"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
