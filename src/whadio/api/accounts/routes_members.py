from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from ...accounts.enums import InvitationRole
from ...accounts.member_repository import WorkspaceMember
from ...shared.pagination import ListCursor
from ..composition import Members
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ErrorCode,
    error_responses,
)
from ..core.pagination import list_page, list_window
from ..core.schemas import Page, PageQuery
from .auth import BrowserUser
from .schemas import USER_ID_EXAMPLE, MemberRead, MemberUpdate, Role, WorkspaceId

router = APIRouter(prefix="/workspaces/{workspace_id}/members", tags=["workspaces"])

MemberId = Annotated[
    UUID, Path(description="The member's user identifier", examples=[USER_ID_EXAMPLE])
]

_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"
_MEMBER_NOT_FOUND = "`NOT_FOUND`: no such workspace or member, or the caller is not a member"
_MODERATOR_ONLY = f"`{ErrorCode.INSUFFICIENT_ROLE}`: Moderator or Owner required"
_OWNER_IMMUTABLE = f"`{ErrorCode.OWNER_IMMUTABLE}`: the member is the Owner"
_REMOVAL_CONFLICT = (
    f"`{ErrorCode.OWNER_IMMUTABLE}`: the member is the Owner; "
    f"`{ErrorCode.RESTRICTED_MEETING_REQUIRES_RECIPIENT}`: the member is the only one selected "
    "for a restricted meeting, so another member must be selected for it first"
)


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


@router.patch(
    "/{user_id}",
    summary="Change a member's role",
    description="Moderator or Owner only. Switches a member between `member` and `moderator`, "
    "with effect from that member's next request. Giving the role the member already has "
    "changes nothing.",
    response_description="The member with their new role",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: DOC_UNAUTHENTICATED,
            403: _MODERATOR_ONLY,
            404: _MEMBER_NOT_FOUND,
            409: _OWNER_IMMUTABLE,
            422: DOC_INVALID,
        }
    ),
)
async def change_member_role(
    workspace_id: WorkspaceId,
    user_id: MemberId,
    payload: MemberUpdate,
    user: BrowserUser,
    members: Members,
) -> MemberRead:
    member = await members.change_role(
        user.id,
        workspace_id,
        user_id,
        InvitationRole(payload.role.value.capitalize()),
        datetime.now(UTC),
    )
    return member_read(member)


@router.delete(
    "/{user_id}",
    status_code=204,
    summary="Remove a member",
    description="Moderator or Owner only, a Moderator's own membership included. The member "
    "loses the workspace and its meetings at once, and their access grants go with the "
    "membership. Refused while they are the only one selected for a restricted meeting; the "
    "refusal names no meeting.",
    response_description="The member was removed",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            403: _MODERATOR_ONLY,
            404: _MEMBER_NOT_FOUND,
            409: _REMOVAL_CONFLICT,
            422: DOC_INVALID,
        }
    ),
)
async def remove_member(
    workspace_id: WorkspaceId, user_id: MemberId, user: BrowserUser, members: Members
) -> Response:
    await members.remove(user.id, workspace_id, user_id, datetime.now(UTC))
    return Response(status_code=204)
