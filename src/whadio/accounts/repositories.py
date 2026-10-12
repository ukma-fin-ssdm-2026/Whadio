import hashlib
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .contracts import UserProfile
from .enums import SessionKind, WorkspaceRole
from .models import McpKey, Session, User, Workspace, WorkspaceMembership


class IMembershipRepository(Protocol):
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def members(self, workspace_id: UUID) -> list[UUID]: ...

    async def profile(self, user_id: UUID) -> UserProfile | None: ...

    async def workspaces(self, user_id: UUID) -> list[UUID]: ...

    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]: ...


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        # NO KEY UPDATE serializes ingests while permitting foreign-key checks on the actor.
        owner = await self._session.scalar(
            select(User.user_id)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.user_id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == WorkspaceRole.OWNER,
            )
            .with_for_update(of=User, key_share=True)
        )
        if owner is None:
            return []
        return list(
            await self._session.scalars(
                select(WorkspaceMembership.workspace_id)
                .where(
                    WorkspaceMembership.user_id == owner,
                    WorkspaceMembership.role == WorkspaceRole.OWNER,
                )
                .order_by(WorkspaceMembership.workspace_id)
            )
        )

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._session.scalar(
            select(WorkspaceMembership.role).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
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

    async def profile(self, user_id: UUID) -> UserProfile | None:
        user = await self._session.get(User, user_id)
        return None if user is None else UserProfile(user.name, user.email)

    async def members(self, workspace_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.workspace_id == workspace_id
                )
            )
        )

    async def workspaces(self, user_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(WorkspaceMembership.workspace_id).where(
                    WorkspaceMembership.user_id == user_id
                )
            )
        )


class IIdentityRepository(Protocol):
    async def session_user(self, token: str, kind: SessionKind, now: datetime) -> User | None: ...

    async def mcp_user(self, token: str, now: datetime) -> User | None: ...


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def session_user(self, token: str, kind: SessionKind, now: datetime) -> User | None:
        return await self._session.scalar(
            select(User)
            .join(Session)
            .where(
                Session.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                Session.kind == kind,
                Session.expires_at > now,
            )
        )

    async def mcp_user(self, token: str, now: datetime) -> User | None:
        return await self._session.scalar(
            select(User)
            .join(McpKey)
            .where(
                McpKey.key_hash == hashlib.sha256(token.encode()).hexdigest(),
                McpKey.revoked_at.is_(None),
                or_(McpKey.expires_at.is_(None), McpKey.expires_at > now),
            )
        )
