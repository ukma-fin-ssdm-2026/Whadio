from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..shared.pagination import ListWindow
from .enums import WorkspaceRole
from .models import User, WorkspaceMembership


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    user_id: UUID
    name: str
    email: str
    role: WorkspaceRole
    joined_at: datetime


class IMemberRepository(Protocol):
    async def page(self, workspace_id: UUID, page: ListWindow, /) -> list[WorkspaceMember]: ...

    async def find(self, workspace_id: UUID, user_id: UUID, /) -> WorkspaceMember | None: ...

    async def set_role(self, workspace_id: UUID, user_id: UUID, role: WorkspaceRole, /) -> None: ...


class MemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def page(self, workspace_id: UUID, page: ListWindow) -> list[WorkspaceMember]:
        """The workspace's members by joining time, oldest first, ties by user id."""
        statement = self._members(workspace_id)
        if page.after is not None:
            joined_at = datetime.fromisoformat(page.after.key)
            statement = statement.where(
                (WorkspaceMembership.joined_at > joined_at)
                | (
                    (WorkspaceMembership.joined_at == joined_at)
                    & (WorkspaceMembership.user_id > page.after.item_id)
                )
            )
        found = await self._session.execute(
            statement.order_by(WorkspaceMembership.joined_at, WorkspaceMembership.user_id).limit(
                page.limit
            )
        )
        return [
            WorkspaceMember(user_id, name, email, role, joined_at)
            for user_id, name, email, role, joined_at in found
        ]

    async def find(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        found = (
            await self._session.execute(
                self._members(workspace_id).where(WorkspaceMembership.user_id == user_id)
            )
        ).one_or_none()
        if found is None:
            return None
        found_id, name, email, role, joined_at = found
        return WorkspaceMember(found_id, name, email, role, joined_at)

    async def set_role(self, workspace_id: UUID, user_id: UUID, role: WorkspaceRole) -> None:
        await self._session.execute(
            update(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
            .values(role=role)
        )

    @staticmethod
    def _members(workspace_id: UUID) -> Select[UUID, str, str, WorkspaceRole, datetime]:
        return (
            select(
                User.user_id,
                User.name,
                User.email,
                WorkspaceMembership.role,
                WorkspaceMembership.joined_at,
            )
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.user_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
        )
