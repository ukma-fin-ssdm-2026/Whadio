from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Folder, Meeting


class IFolderRepository(Protocol):
    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None: ...

    async def default_folder(self, workspace_id: UUID) -> Folder | None: ...

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]: ...

    async def remove_folder(self, folder_id: UUID) -> None: ...


class FolderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.folder_id == folder_id)
            .with_for_update()
        )

    async def default_folder(self, workspace_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.is_default)
            .with_for_update()
        )

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                update(Meeting)
                .where(Meeting.folder_id == folder_id)
                .values(folder_id=destination_id)
                .returning(Meeting.meeting_id)
            )
        )

    async def remove_folder(self, folder_id: UUID) -> None:
        await self._session.execute(delete(Folder).where(Folder.folder_id == folder_id))
