from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Query, Request, Response

from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    error_responses,
)
from ..core.schemas import Page, PageQuery, paginate
from .auth import BrowserUser
from .fixtures import WORKSPACES, workspace
from .schemas import (
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


@router.get(
    "/workspaces",
    summary="List my workspaces",
    description="Workspaces the caller belongs to, oldest first, the personal one included.",
    response_description="A page of workspaces",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def list_workspaces(
    query: Annotated[PageQuery, Query()], _user: BrowserUser
) -> Page[WorkspaceSummary]:
    workspaces: list[WorkspaceSummary] = [*WORKSPACES.values()]
    return paginate(workspaces, query)


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
    payload: WorkspaceCreate, _user: BrowserUser, request: Request, response: Response
) -> WorkspaceRead:
    created = WorkspaceRead(
        id=uuid4(),
        name=payload.name,
        is_personal=False,
        my_role=Role.OWNER,
        member_count=1,
        notes_provider=Provider.WHADIO,
        created_at=datetime.now(UTC),
        default_preset=payload.default_preset,
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
async def get_workspace(workspace_id: WorkspaceId, _user: BrowserUser) -> WorkspaceRead:
    return workspace(workspace_id)


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
    workspace_id: WorkspaceId, payload: WorkspaceUpdate, _user: BrowserUser
) -> WorkspaceRead:
    return workspace(workspace_id).model_copy(update=payload.model_dump(exclude_none=True))


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
async def delete_workspace(workspace_id: WorkspaceId, _user: BrowserUser) -> None:
    if workspace(workspace_id).is_personal:
        raise ApiError(409, ErrorCode.PERSONAL_WORKSPACE, "A personal workspace cannot be deleted")
