from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Folder, Meeting


class IMeetingMetadata(Protocol):
    def in_workspace(self, workspace_id: UUID) -> Select[UUID]: ...

    async def workspaces(self, meeting_ids: list[UUID]) -> dict[UUID, UUID]: ...


class MeetingMetadata:
    """Operational IDs only; never offers content or a bypass of content authorization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    def in_workspace(self, workspace_id: UUID) -> Select[UUID]:
        return select(Meeting.meeting_id).join(Folder).where(Folder.workspace_id == workspace_id)

    async def workspaces(self, meeting_ids: list[UUID]) -> dict[UUID, UUID]:
        rows = await self._session.execute(
            select(Meeting.meeting_id, Folder.workspace_id)
            .join(Folder)
            .where(Meeting.meeting_id.in_(meeting_ids))
        )
        return dict(rows.all())
