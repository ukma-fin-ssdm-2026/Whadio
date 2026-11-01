from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from ...accounts.enums import InvitationRole, RegistrationMode
from ...accounts.services import InvitationRequest
from ...shared.pagination import ListCursor
from ..composition import Invitations, invitation_public_url, registration_mode
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
from .invitation_mapping import invitation_read
from .schemas import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    WorkspaceId,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/invitations", tags=["workspaces"])

_NOT_FOUND = "`NOT_FOUND`: no such workspace, invitation, or caller membership"
_MODERATOR_ONLY = f"`{ErrorCode.INSUFFICIENT_ROLE}`: Moderator or Owner required"


@router.get(
    "",
    summary="List pending invitations",
    description="Moderator or Owner only. Lists pending invitations newest first. Secrets and "
    "links are never returned.",
    response_description="A page of pending invitations",
    responses=error_responses(
        {401: DOC_UNAUTHENTICATED, 403: _MODERATOR_ONLY, 404: _NOT_FOUND, 422: DOC_INVALID}
    ),
)
async def list_invitations(
    workspace_id: WorkspaceId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    invitations: Invitations,
) -> Page[InvitationRead]:
    scope = f"workspace-invitations:{workspace_id}:{user.id}:newest"
    found = await invitations.list_pending(
        user.id, workspace_id, list_window(query, scope, chronological=True)
    )
    last = found[min(len(found), query.limit) - 1] if found else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.invitation_id)
    now = datetime.now(UTC)
    return list_page(
        [invitation_read(item, link_active=item.link_active(now)) for item in found],
        query,
        scope,
        cursor,
    )


@router.post(
    "",
    status_code=201,
    summary="Invite a workspace member",
    description="Moderator or Owner only. Creates a seven-day, single-use invitation. Issuing "
    "another pending invitation to the same email replaces it and invalidates its old link.",
    response_description="The invitation and its one-time link",
    responses={
        200: {"model": InvitationCreated, "description": "Replaced pending invitation"},
        **error_responses(
            {
                400: DOC_MALFORMED,
                401: DOC_UNAUTHENTICATED,
                403: _MODERATOR_ONLY,
                404: _NOT_FOUND,
                409: "`PERSONAL_WORKSPACE`, or `ALREADY_MEMBER`",
                422: DOC_INVALID,
                429: "`INVITATION_LIMIT` or `INVITATION_COOLDOWN`; see `Retry-After`",
                503: "`INTEGRATION_UNAVAILABLE`: public URL is unset or verified-mode email "
                "delivery is unavailable",
            }
        ),
    },
)
async def create_invitation(
    workspace_id: WorkspaceId,
    payload: InvitationCreate,
    user: BrowserUser,
    invitations: Invitations,
    response: Response,
    mode: Annotated[RegistrationMode, Depends(registration_mode)],
    public_url: Annotated[str, Depends(invitation_public_url)],
) -> InvitationCreated:
    now = datetime.now(UTC)
    issued = await invitations.invite(
        user.id,
        workspace_id,
        InvitationRequest(
            str(payload.email), InvitationRole(payload.role.value.capitalize()), mode
        ),
        now,
    )
    if issued.replaced:
        response.status_code = 200
    invitation = invitation_read(issued.invitation, link_active=issued.invitation.link_active(now))
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        link_active=invitation.link_active,
        link=issued.url(public_url) if mode is RegistrationMode.INVITE_ONLY else None,
    )


@router.post(
    "/{invitation_id}/cancel",
    summary="Cancel an invitation",
    description="Moderator or Owner only. Cancels a pending invitation and invalidates its link.",
    response_description="The cancelled invitation",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            403: _MODERATOR_ONLY,
            404: _NOT_FOUND,
            409: "`INVITATION_NOT_PENDING`: the invitation was already answered or cancelled",
            422: DOC_INVALID,
        }
    ),
)
async def cancel_invitation(
    workspace_id: WorkspaceId,
    invitation_id: Annotated[UUID, Path(description="Invitation identifier")],
    user: BrowserUser,
    invitations: Invitations,
) -> InvitationRead:
    now = datetime.now(UTC)
    invitation = await invitations.cancel(user.id, workspace_id, invitation_id, now)
    return invitation_read(invitation, link_active=invitation.link_active(now))
