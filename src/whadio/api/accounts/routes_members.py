from typing import Annotated

from fastapi import APIRouter, Query

from ...accounts.member_repository import WorkspaceMember
from ...shared.pagination import ListCursor
from ..composition import Members
from ..core.errors import DOC_INVALID, DOC_UNAUTHENTICATED, error_responses
from ..core.pagination import list_page, list_window
from ..core.schemas import Page, PageQuery
from .auth import BrowserUser
from .schemas import MemberRead, Role, WorkspaceId

router = APIRouter(prefix="/workspaces/{workspace_id}/members", tags=["workspaces"])

_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"


def member_read(member: WorkspaceMember) -> MemberRead:
    return MemberRead(
        user_id=member.user_id,
        name=member.name,
        email=member.email,
        role=Role(member.role.value.lower()),
        joined_at=member.joined_at,
    )


@router.get(
    "",
    summary="List members",
    description="Any member. Lists the workspace's members by joining time, oldest first.",
    response_description="A page of members",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 404: _NOT_FOUND, 422: DOC_INVALID}),
)
async def list_members(
    workspace_id: WorkspaceId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    members: Members,
) -> Page[MemberRead]:
    scope = f"workspace-members:{workspace_id}:{user.id}:joined"
    found = await members.list(user.id, workspace_id, list_window(query, scope, chronological=True))
    last = found[min(len(found), query.limit) - 1] if found else None
    cursor = None if last is None else ListCursor(last.joined_at.isoformat(), last.user_id)
    return list_page([member_read(item) for item in found], query, scope, cursor)
