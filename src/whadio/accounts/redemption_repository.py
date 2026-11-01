from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import InvitationStatus, WorkspaceRole
from .models import Invitation, User, Workspace, WorkspaceMembership


@dataclass(frozen=True)
class InvitationLink:
    invitation: Invitation
    workspace_name: str


class IRedemptionRepository(Protocol):
    async def find(self, invitation_id: UUID) -> InvitationLink | None: ...

    async def lock(self, invitation_id: UUID) -> Invitation | None: ...

    async def account_exists(self, email: str) -> bool: ...

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership | None: ...

    async def join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership: ...

    async def answer(
        self, invitation: Invitation, status: InvitationStatus, now: datetime
    ) -> None: ...


class RedemptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def find(self, invitation_id: UUID) -> InvitationLink | None:
        row = (
            await self._session.execute(
                select(Invitation, Workspace.name)
                .join(Workspace, Workspace.workspace_id == Invitation.workspace_id)
                .where(Invitation.invitation_id == invitation_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        return None if row is None else InvitationLink(row[0], row[1])

    async def lock(self, invitation_id: UUID) -> Invitation | None:
        link = await self.find(invitation_id)
        if link is None:
            return None
        # Match management's workspace-before-invitation order, including role changes in #184.
        await self._session.scalar(
            select(Workspace.workspace_id)
            .where(Workspace.workspace_id == link.invitation.workspace_id)
            .with_for_update()
        )
        return await self._session.scalar(
            select(Invitation)
            .where(Invitation.invitation_id == invitation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def account_exists(self, email: str) -> bool:
        return bool(
            await self._session.scalar(
                select(select(User.user_id).where(func.lower(User.email) == email.lower()).exists())
            )
        )

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership | None:
        return await self._session.scalar(
            select(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )

    async def join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership:
        member = WorkspaceMembership(
            workspace_id=invitation.workspace_id,
            user_id=user_id,
            role=WorkspaceRole(invitation.role.value),
            joined_at=now,
        )
        self._session.add(member)
        await self.answer(invitation, InvitationStatus.ACCEPTED, now)
        return member

    async def answer(self, invitation: Invitation, status: InvitationStatus, now: datetime) -> None:
        invitation.status = status
        invitation.responded_at = now
        await self._session.flush()
