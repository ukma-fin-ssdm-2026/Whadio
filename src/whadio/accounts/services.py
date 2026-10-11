from datetime import datetime
from typing import Protocol
from uuid import UUID

from .contracts import UserProfile
from .enums import SessionKind, WorkspaceRole
from .models import User
from .repositories import IIdentityRepository, IMembershipRepository


class IWorkspaceMembership(Protocol):
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...


class IWorkspaceDirectory(IWorkspaceMembership, Protocol):
    async def members(self, workspace_id: UUID) -> list[UUID]: ...

    async def profile(self, user_id: UUID) -> UserProfile | None: ...

    async def workspaces(self, user_id: UUID) -> list[UUID]: ...


class IWorkspaceCapacity(Protocol):
    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        """Lock the Owner across concurrent ingests, then return all their workspaces."""
        ...


class WorkspaceMembershipService:
    def __init__(self, repository: IMembershipRepository) -> None:
        self._repository: IMembershipRepository = repository

    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        return await self._repository.capacity_workspaces(workspace_id)

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.role(workspace_id, user_id)

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.lock_role(workspace_id, user_id)

    async def members(self, workspace_id: UUID) -> list[UUID]:
        return await self._repository.members(workspace_id)

    async def profile(self, user_id: UUID) -> UserProfile | None:
        return await self._repository.profile(user_id)

    async def workspaces(self, user_id: UUID) -> list[UUID]:
        return await self._repository.workspaces(user_id)


class IdentityService:
    def __init__(self, repository: IIdentityRepository) -> None:
        self._repository: IIdentityRepository = repository

    async def session_user(self, token: str, kind: SessionKind, now: datetime) -> User | None:
        return await self._repository.session_user(token, kind, now)

    async def mcp_user(self, token: str, now: datetime) -> User | None:
        return await self._repository.mcp_user(token, now)
