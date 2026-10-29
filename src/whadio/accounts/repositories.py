import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..shared.pagination import ListWindow
from .contracts import UserProfile
from .enums import NotesTemplate, SessionKind, WorkspaceRole
from .models import McpKey, PendingRegistration, Session, User, Workspace, WorkspaceMembership


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
        self, user_id: UUID, kind: SessionKind, token: str, expires_at: datetime, now: datetime, /
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
            select(User)
            .where(func.lower(User.email) == email.lower())
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )

    async def add_session(
        self, user_id: UUID, kind: SessionKind, token: str, expires_at: datetime, now: datetime
    ) -> None:
        self._session.add(
            Session(
                user_id=user_id,
                kind=kind,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=expires_at,
                created_at=now,
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


# --- MCP keys ---


@dataclass(frozen=True, slots=True)
class PersonalMcpKey:
    key_id: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


class McpKeyRevokeResult(StrEnum):
    NOT_FOUND = "not_found"
    ALREADY_REVOKED = "already_revoked"
    REVOKED = "revoked"


class IMcpKeyRepository(Protocol):
    async def of_user(
        self, user_id: UUID, page: ListWindow | None = None, /
    ) -> list[PersonalMcpKey]: ...

    async def add(
        self, user_id: UUID, key_hash: str, expires_at: datetime | None, now: datetime, /
    ) -> PersonalMcpKey: ...

    async def revoke(self, user_id: UUID, key_id: UUID, now: datetime, /) -> McpKeyRevokeResult: ...


class McpKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def of_user(self, user_id: UUID, page: ListWindow | None = None) -> list[PersonalMcpKey]:
        statement = select(McpKey).where(McpKey.user_id == user_id)
        if page is not None:
            if page.after is not None:
                created_at = datetime.fromisoformat(page.after.key)
                statement = statement.where(
                    (McpKey.created_at < created_at)
                    | ((McpKey.created_at == created_at) & (McpKey.mcp_key_id < page.after.item_id))
                )
            statement = statement.limit(page.limit)
        keys = await self._session.scalars(
            statement.order_by(McpKey.created_at.desc(), McpKey.mcp_key_id.desc())
        )
        return [self._read(key) for key in keys]

    async def add(
        self, user_id: UUID, key_hash: str, expires_at: datetime | None, now: datetime
    ) -> PersonalMcpKey:
        key = McpKey(
            user_id=user_id,
            key_hash=key_hash,
            created_at=now,
            expires_at=expires_at,
            revoked_at=None,
        )
        self._session.add(key)
        await self._session.flush()
        return self._read(key)

    async def revoke(self, user_id: UUID, key_id: UUID, now: datetime) -> McpKeyRevokeResult:
        key = await self._session.scalar(
            select(McpKey)
            .where(McpKey.mcp_key_id == key_id, McpKey.user_id == user_id)
            .with_for_update()
        )
        if key is None:
            return McpKeyRevokeResult.NOT_FOUND
        if key.revoked_at is not None:
            return McpKeyRevokeResult.ALREADY_REVOKED
        key.revoked_at = now
        await self._session.flush()
        return McpKeyRevokeResult.REVOKED

    @staticmethod
    def _read(key: McpKey) -> PersonalMcpKey:
        return PersonalMcpKey(
            key_id=key.mcp_key_id,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
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
        self,
        name: str,
        template: NotesTemplate,
        owner_id: UUID,
        now: datetime,
        /,
        *,
        personal: bool = False,
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

    async def add(
        self,
        name: str,
        template: NotesTemplate,
        owner_id: UUID,
        now: datetime,
        *,
        personal: bool = False,
    ) -> UUID:
        workspace = Workspace(
            name=name, default_template=template, is_personal=personal, created_at=now
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


# --- Registration ---


class IRegistrationRepository(Protocol):
    async def lock_email(self, email: str, /) -> None: ...

    async def pending(self, registration_id: UUID, /) -> PendingRegistration | None: ...

    async def issue(
        self, email: str, token_hash: str, now: datetime, expires_at: datetime, /
    ) -> UUID: ...

    async def create_account(
        self, email: str, name: str, password_hash: str, now: datetime, /
    ) -> User: ...

    async def delete_expired(self, now: datetime, /) -> int: ...


class RegistrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def lock_email(self, email: str) -> None:
        # A row lock cannot serialize first issuance: no pending row exists yet.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(lower(:email), 0))"),
            {"email": email},
        )

    async def pending(self, registration_id: UUID) -> PendingRegistration | None:
        return await self._session.scalar(
            select(PendingRegistration)
            .where(PendingRegistration.pending_registration_id == registration_id)
            .execution_options(populate_existing=True)
        )

    async def issue(self, email: str, token_hash: str, now: datetime, expires_at: datetime) -> UUID:
        pending = await self._session.scalar(
            select(PendingRegistration).where(
                func.lower(PendingRegistration.email) == email.lower()
            )
        )
        if pending is None:
            pending = PendingRegistration(email=email)
            self._session.add(pending)
        pending.token_hash = token_hash
        pending.created_at = now
        pending.expires_at = expires_at
        await self._session.flush()
        return pending.pending_registration_id

    async def create_account(
        self, email: str, name: str, password_hash: str, now: datetime
    ) -> User:
        await self._session.execute(
            delete(PendingRegistration).where(
                func.lower(PendingRegistration.email) == email.lower()
            )
        )
        user = User(
            email=email,
            name=name,
            password_hash=password_hash,
            terms_accepted_at=now,
            created_at=now,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def delete_expired(self, now: datetime) -> int:
        deleted = await self._session.scalars(
            delete(PendingRegistration)
            .where(PendingRegistration.expires_at <= now)
            .returning(PendingRegistration.pending_registration_id)
        )
        return len(deleted.all())
