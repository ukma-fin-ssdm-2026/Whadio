import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .contracts import UserProfile
from .enums import NotesTemplate, SessionKind, WorkspaceRole
from .models import McpKey, Session, User, Workspace, WorkspaceMembership


class IWorkspaceSettingsRepository(Protocol):
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


# --- Signing in ---


class ISessionRepository(Protocol):
    async def by_email(self, email: str, /) -> User | None: ...

    async def add_session(
        self, user_id: UUID, kind: SessionKind, token: str, expires_at: datetime, /
    ) -> None: ...

    async def end_sessions(self, tokens: Collection[str], /) -> None: ...

    async def end_expired_sessions(self, user_id: UUID, now: datetime, /) -> None: ...


class SessionRepository:
    """Stores a session token only as its SHA-256 hash, as `IdentityRepository` looks it up."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def by_email(self, email: str) -> User | None:
        # The unique index is on lower(email), so this finds the address whatever its case.
        return await self._session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )

    async def add_session(
        self, user_id: UUID, kind: SessionKind, token: str, expires_at: datetime
    ) -> None:
        self._session.add(
            Session(
                user_id=user_id,
                kind=kind,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def end_sessions(self, tokens: Collection[str]) -> None:
        await self._session.execute(
            delete(Session).where(
                Session.token_hash.in_(
                    [hashlib.sha256(token.encode()).hexdigest() for token in tokens]
                )
            )
        )

    async def end_expired_sessions(self, user_id: UUID, now: datetime) -> None:
        await self._session.execute(
            delete(Session).where(Session.user_id == user_id, Session.expires_at <= now)
        )


# --- Workspaces ---


@dataclass(frozen=True, slots=True)
class MemberWorkspace:
    workspace_id: UUID
    name: str
    is_personal: bool
    role: WorkspaceRole
    member_count: int
    default_template: NotesTemplate
    created_at: datetime


class IWorkspaceRepository(Protocol):
    async def of_member(
        self, user_id: UUID, workspace_id: UUID | None, /
    ) -> list[MemberWorkspace]: ...

    async def add(
        self, name: str, template: NotesTemplate, owner_id: UUID, now: datetime, /
    ) -> UUID: ...

    async def update(
        self, workspace_id: UUID, name: str | None, template: NotesTemplate | None, /
    ) -> None: ...

    async def remove(self, workspace_id: UUID, /) -> None: ...


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def of_member(self, user_id: UUID, workspace_id: UUID | None) -> list[MemberWorkspace]:
        """The member's workspaces, oldest first, or only `workspace_id` when given."""
        others = aliased(WorkspaceMembership)
        member_count = (
            select(func.count())
            .where(others.workspace_id == Workspace.workspace_id)
            .scalar_subquery()
        )
        statement = (
            select(Workspace, WorkspaceMembership.role, member_count)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(Workspace.created_at, Workspace.workspace_id)
        )
        if workspace_id is not None:
            statement = statement.where(Workspace.workspace_id == workspace_id)
        return [
            MemberWorkspace(
                workspace_id=workspace.workspace_id,
                name=workspace.name,
                is_personal=workspace.is_personal,
                role=role,
                member_count=count,
                default_template=workspace.default_template,
                created_at=workspace.created_at,
            )
            for workspace, role, count in await self._session.execute(statement)
        ]

    async def add(self, name: str, template: NotesTemplate, owner_id: UUID, now: datetime) -> UUID:
        workspace = Workspace(
            name=name, default_template=template, is_personal=False, created_at=now
        )
        self._session.add(workspace)
        await self._session.flush()
        self._session.add(
            WorkspaceMembership(
                workspace_id=workspace.workspace_id,
                user_id=owner_id,
                role=WorkspaceRole.OWNER,
                joined_at=now,
            )
        )
        await self._session.flush()
        return workspace.workspace_id

    async def update(
        self, workspace_id: UUID, name: str | None, template: NotesTemplate | None
    ) -> None:
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            return
        if name is not None:
            workspace.name = name
        if template is not None:
            workspace.default_template = template
        await self._session.flush()

    async def remove(self, workspace_id: UUID) -> None:
        # Folders and memberships go with it through ON DELETE CASCADE.
        await self._session.execute(delete(Workspace).where(Workspace.workspace_id == workspace_id))
