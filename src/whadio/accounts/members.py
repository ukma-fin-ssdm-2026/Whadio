from uuid import UUID

from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .member_repository import IMemberRepository, WorkspaceMember
from .services import IWorkspaceMembership


class MemberService:
    def __init__(self, members: IMemberRepository, memberships: IWorkspaceMembership) -> None:
        self._members: IMemberRepository = members
        self._memberships: IWorkspaceMembership = memberships

    async def list(
        self, actor_id: UUID, workspace_id: UUID, page: ListWindow
    ) -> list[WorkspaceMember]:
        if await self._memberships.role(workspace_id, actor_id) is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return await self._members.page(workspace_id, page)
