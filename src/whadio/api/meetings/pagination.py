import base64
import binascii
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from ...meetings.contracts import MeetingFilter
from ...shared.errors import Failure, UseCaseError
from ..core.schemas import Page, PageInfo
from .schemas import MeetingListQuery, MeetingSummary


class MeetingCursor(BaseModel):
    workspace_id: UUID = Field(description="Workspace the cursor belongs to")
    recorded_at: AwareDatetime = Field(description="Last meeting timestamp")
    meeting_id: UUID = Field(description="Last meeting identifier")


def meeting_filter(workspace_id: UUID, query: MeetingListQuery) -> MeetingFilter:
    after = None
    if query.cursor is not None:
        try:
            encoded = query.cursor + "=" * (-len(query.cursor) % 4)
            cursor = MeetingCursor.model_validate_json(
                base64.b64decode(encoded, altchars=b"-_", validate=True)
            )
        except (ValueError, ValidationError, binascii.Error):
            raise UseCaseError(Failure.VALIDATION_ERROR) from None
        if cursor.workspace_id != workspace_id:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        after = (cursor.recorded_at, cursor.meeting_id)
    return MeetingFilter(
        workspace_id,
        query.folder_id,
        query.name,
        query.recorded_from,
        query.recorded_to,
        query.limit + 1,
        after,
    )


def meeting_page(items: list[MeetingSummary], limit: int) -> Page[MeetingSummary]:
    next_cursor = None
    if len(items) > limit:
        last = items[limit - 1]
        cursor = MeetingCursor(
            workspace_id=last.workspace_id, recorded_at=last.recorded_at, meeting_id=last.id
        )
        next_cursor = (
            base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")
        )
    return Page(
        items=items[:limit],
        pagination=PageInfo(limit=limit, next_cursor=next_cursor, has_more=len(items) > limit),
    )
