from typing import Protocol
from uuid import UUID

from .enums import WorkspaceRole
from .repositories import IMembershipRepository


class IWorkspaceMembership(Protocol):
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...


class WorkspaceMembershipService:
    def __init__(self, repository: IMembershipRepository) -> None:
        self._repository: IMembershipRepository = repository

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.role(workspace_id, user_id)

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.lock_role(workspace_id, user_id)
