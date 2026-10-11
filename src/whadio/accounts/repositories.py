from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import NotesTemplate, WorkspaceRole
from .models import Workspace, WorkspaceMembership


class IWorkspaceSettings(Protocol):
    async def default_template(self, workspace_id: UUID, /) -> NotesTemplate | None: ...


class WorkspaceSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def default_template(self, workspace_id: UUID) -> NotesTemplate | None:
        return await self._session.scalar(
            select(Workspace.default_template).where(Workspace.workspace_id == workspace_id)
        )


class IMembershipRepository(Protocol):
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._session.scalar(
            select(WorkspaceMembership.role).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        # Serialize folder deletion with workspace deletion and role changes.
        await self._session.scalar(
            select(Workspace.workspace_id)
            .where(Workspace.workspace_id == workspace_id)
            .with_for_update()
        )
        return await self._session.scalar(
            select(WorkspaceMembership.role)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
            .with_for_update()
        )
