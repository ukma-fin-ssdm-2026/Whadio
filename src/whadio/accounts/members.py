from dataclasses import replace
from datetime import datetime
from uuid import UUID

from ..audit.services import IMembershipAuditWriter, MemberRoleChanged
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .enums import InvitationRole, WorkspaceRole
from .member_repository import IMemberRepository, WorkspaceMember
from .services import IWorkspaceMembership


class MemberService:
    def __init__(
        self,
        members: IMemberRepository,
        memberships: IWorkspaceMembership,
        audit: IMembershipAuditWriter,
    ) -> None:
        self._members: IMemberRepository = members
        self._memberships: IWorkspaceMembership = memberships
        self._audit: IMembershipAuditWriter = audit

    async def list(
        self, actor_id: UUID, workspace_id: UUID, page: ListWindow
    ) -> list[WorkspaceMember]:
        if await self._memberships.role(workspace_id, actor_id) is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return await self._members.page(workspace_id, page)

    async def change_role(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        role: InvitationRole,
        now: datetime,
    ) -> WorkspaceMember:
        member = await self._managed(actor_id, workspace_id, user_id)
        new_role = WorkspaceRole(role.value)
        if member.role is new_role:
            return member
        await self._members.set_role(workspace_id, user_id, new_role)
        await self._audit.write(
            MemberRoleChanged(
                actor_id, workspace_id, user_id, member.role.value, new_role.value, now
            )
        )
        return replace(member, role=new_role)

    async def _managed(self, actor_id: UUID, workspace_id: UUID, user_id: UUID) -> WorkspaceMember:
        # Every membership change locks the workspace first, so the roles read here hold.
        actor_role = await self._memberships.lock_role(workspace_id, actor_id)
        if actor_role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if actor_role is WorkspaceRole.MEMBER:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        member = await self._members.find(workspace_id, user_id)
        if member is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if member.role is WorkspaceRole.OWNER:
            raise UseCaseError(Failure.OWNER_IMMUTABLE)
        return member
