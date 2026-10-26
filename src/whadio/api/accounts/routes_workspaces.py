from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from ...accounts.enums import NotesTemplate
from ...accounts.repositories import MemberWorkspace
from ..composition import Workspaces
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ErrorCode,
    error_responses,
)
from ..core.schemas import Page, PageQuery, paginate
from .auth import BrowserUser
from .schemas import (
    Preset,
    Provider,
    Role,
    WorkspaceCreate,
    WorkspaceId,
    WorkspaceRead,
    WorkspaceSummary,
    WorkspaceUpdate,
)

router = APIRouter(tags=["workspaces"])

_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"
_OWNER_ONLY = f"`{ErrorCode.INSUFFICIENT_ROLE}`: only the Owner can do this"


def workspace_read(found: MemberWorkspace) -> WorkspaceRead:
    return WorkspaceRead(
        id=found.workspace_id,
        name=found.name,
        is_personal=found.is_personal,
        my_role=Role(found.role.value.lower()),
        member_count=found.member_count,
        # Only the built-in model writes notes until workspaces can choose a provider.
        notes_provider=Provider.WHADIO,
        created_at=found.created_at,
        default_preset=Preset(found.default_template.value),
    )


@router.get(
    "/workspaces",
    summary="List my workspaces",
    description="Workspaces the caller belongs to, oldest first, the personal one included.",
    response_description="A page of workspaces",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def list_workspaces(
    query: Annotated[PageQuery, Query()], user: BrowserUser, workspaces: Workspaces
) -> Page[WorkspaceSummary]:
    found: list[WorkspaceSummary] = [
        workspace_read(item) for item in await workspaces.list_workspaces(user.id)
    ]
    return paginate(found, query)


@router.post(
    "/workspaces",
    status_code=201,
    summary="Create a workspace",
    description="Creates a workspace with the caller as its Owner, one default folder and no "
    "meetings.",
    response_description="The new workspace",
    responses={
        201: {
            "headers": {
                "Location": {
                    "description": "URL of the new workspace",
                    "schema": {"type": "string", "format": "uri"},
                }
            }
        },
        **error_responses({400: DOC_MALFORMED, 401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
    },
)
async def create_workspace(
    payload: WorkspaceCreate,
    user: BrowserUser,
    workspaces: Workspaces,
    request: Request,
    response: Response,
) -> WorkspaceRead:
    created = workspace_read(
        await workspaces.create(
            user.id,
            payload.name,
            NotesTemplate(payload.default_preset.value),
            datetime.now(UTC),
        )
    )
    response.headers["Location"] = str(request.url_for("get_workspace", workspace_id=created.id))
    return created


@router.get(
    "/workspaces/{workspace_id}",
    summary="Get a workspace",
    description="Any member. Includes the caller's role and where notes are generated.",
    response_description="The workspace",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 404: _NOT_FOUND, 422: DOC_INVALID}),
)
async def get_workspace(
    workspace_id: WorkspaceId, user: BrowserUser, workspaces: Workspaces
) -> WorkspaceRead:
    return workspace_read(await workspaces.get(user.id, workspace_id))


@router.patch(
    "/workspaces/{workspace_id}",
    summary="Update workspace settings",
    description="Owner only. Renames the workspace or changes its default notes preset; give "
    "at least one field.",
    response_description="The updated workspace",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: DOC_UNAUTHENTICATED,
            403: _OWNER_ONLY,
            404: _NOT_FOUND,
            422: DOC_INVALID,
        }
    ),
)
async def update_workspace(
    workspace_id: WorkspaceId,
    payload: WorkspaceUpdate,
    user: BrowserUser,
    workspaces: Workspaces,
) -> WorkspaceRead:
    return workspace_read(
        await workspaces.update(
            user.id,
            workspace_id,
            payload.name,
            None if payload.default_preset is None else NotesTemplate(payload.default_preset.value),
        )
    )


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=204,
    summary="Delete a workspace",
    description="Owner only. Deletes the workspace with its folders, meetings, recordings, "
    "transcripts and notes. A personal workspace cannot be deleted.",
    response_description="Deleted",
    responses=error_responses(
        {
            401: DOC_UNAUTHENTICATED,
            403: _OWNER_ONLY,
            404: _NOT_FOUND,
            409: f"`{ErrorCode.PERSONAL_WORKSPACE}`: a personal workspace cannot be deleted",
            422: DOC_INVALID,
        }
    ),
)
async def delete_workspace(
    workspace_id: WorkspaceId, user: BrowserUser, workspaces: Workspaces
) -> None:
    await workspaces.delete(user.id, workspace_id, datetime.now(UTC))
