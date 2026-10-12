import asyncio
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from ..audit.services import IWorkspaceAuditWriter, WorkspaceDeleted
from ..shared.errors import Failure, UseCaseError
from .contracts import UserProfile
from .enums import NotesTemplate, SessionKind, WorkspaceRole
from .models import User
from .passwords import IPasswordHasher
from .repositories import (
    IIdentityRepository,
    IMembershipRepository,
    ISessionRepository,
    IWorkspaceRepository,
    IWorkspaceSettingsRepository,
    MemberWorkspace,
)

SESSION_LIFETIMES: Final = {
    SessionKind.BROWSER: timedelta(days=14),
    SessionKind.EXTENSION: timedelta(hours=24),
}


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


class IWorkspaceSettings(Protocol):
    async def default_template(self, workspace_id: UUID, /) -> NotesTemplate: ...


class WorkspaceSettingsService:
    def __init__(self, repository: IWorkspaceSettingsRepository) -> None:
        self._repository: IWorkspaceSettingsRepository = repository

    async def default_template(self, workspace_id: UUID) -> NotesTemplate:
        return await self._repository.default_template(workspace_id) or NotesTemplate.SUMMARY


# --- Signing in ---


@dataclass(frozen=True, slots=True)
class SignedIn:
    token: str
    expires_at: datetime
    user: User


class SignInService:
    def __init__(self, sessions: ISessionRepository, passwords: IPasswordHasher) -> None:
        self._sessions: ISessionRepository = sessions
        self._passwords: IPasswordHasher = passwords

    async def sign_in(
        self, email: str, password: str, kind: SessionKind, now: datetime
    ) -> SignedIn:
        user = await self._sessions.by_email(email)
        # Argon2 takes tens of milliseconds of CPU, so it runs off the event loop.
        if user is None:
            # Costs what a wrong password costs, so the timing does not tell which was wrong.
            await asyncio.to_thread(self._passwords.hash, password)
            raise UseCaseError(Failure.INVALID_CREDENTIALS)
        if not await asyncio.to_thread(self._passwords.verify, user.password_hash, password):
            raise UseCaseError(Failure.INVALID_CREDENTIALS)
        await self._sessions.end_expired_sessions(user.user_id, now)
        token = secrets.token_urlsafe(32)
        expires_at = now + SESSION_LIFETIMES[kind]
        await self._sessions.add_session(user.user_id, kind, token, expires_at)
        return SignedIn(token, expires_at, user)

    async def sign_out(self, tokens: Collection[str]) -> None:
        await self._sessions.end_sessions(tokens)


# --- Workspaces ---


class IWorkspaceContent(Protocol):
    """What a workspace holds in modules above Accounts; Meetings implements it."""

    async def add_default_folder(self, workspace_id: UUID, now: datetime, /) -> None: ...

    async def remove_meetings(self, workspace_id: UUID, now: datetime, /) -> None: ...


class WorkspaceService:
    def __init__(
        self,
        workspaces: IWorkspaceRepository,
        memberships: IWorkspaceMembership,
        content: IWorkspaceContent,
        audit: IWorkspaceAuditWriter,
    ) -> None:
        self._workspaces: IWorkspaceRepository = workspaces
        self._memberships: IWorkspaceMembership = memberships
        self._content: IWorkspaceContent = content
        self._audit: IWorkspaceAuditWriter = audit

    async def list_workspaces(self, user_id: UUID) -> list[MemberWorkspace]:
        return await self._workspaces.of_member(user_id, None)

    async def get(self, user_id: UUID, workspace_id: UUID) -> MemberWorkspace:
        found = await self._workspaces.of_member(user_id, workspace_id)
        if not found:
            raise UseCaseError(Failure.NOT_FOUND)
        return found[0]

    async def create(
        self, user_id: UUID, name: str, template: NotesTemplate, now: datetime
    ) -> MemberWorkspace:
        workspace_id = await self._workspaces.add(name, template, user_id, now)
        await self._content.add_default_folder(workspace_id, now)
        return await self.get(user_id, workspace_id)

    async def update(
        self, user_id: UUID, workspace_id: UUID, name: str | None, template: NotesTemplate | None
    ) -> MemberWorkspace:
        await self._owned(user_id, workspace_id)
        await self._workspaces.update(workspace_id, name, template)
        return await self.get(user_id, workspace_id)

    async def delete(self, user_id: UUID, workspace_id: UUID, now: datetime) -> None:
        """Queues the workspace's recordings for deletion from storage once this commits."""
        if (await self._owned(user_id, workspace_id)).is_personal:
            raise UseCaseError(Failure.PERSONAL_WORKSPACE)
        await self._content.remove_meetings(workspace_id, now)
        await self._audit.write(WorkspaceDeleted(user_id, workspace_id, now))
        await self._workspaces.remove(workspace_id)

    async def _owned(self, user_id: UUID, workspace_id: UUID) -> MemberWorkspace:
        # Locked, the role cannot change between this check and the change it allows.
        role = await self._memberships.lock_role(workspace_id, user_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role is not WorkspaceRole.OWNER:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        return await self.get(user_id, workspace_id)
