from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased

from ..audit.models import AuditAction, AuditEvent
from ..core.db import Db
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    error_responses,
    not_found,
)
from ..core.schemas import Page, PageQuery, paginate
from ..meetings.models import Folder, Meeting
from .auth import BrowserUser
from .models import Workspace, WorkspaceMembership
from .schemas import (
    Provider,
    Role,
    UserRead,
    WorkspaceCreate,
    WorkspaceId,
    WorkspaceRead,
    WorkspaceSummary,
    WorkspaceUpdate,
)

router = APIRouter(tags=["workspaces"])

_NOT_FOUND = "`NOT_FOUND`: no such workspace, or the caller is not a member"
_OWNER_ONLY = f"`{ErrorCode.INSUFFICIENT_ROLE}`: only the Owner can do this"


async def _my_workspaces(
    db: Db, user: UserRead, workspace_id: UUID | None = None
) -> list[WorkspaceRead]:
    """The caller's workspaces, oldest first, or just `workspace_id` if they are a member."""
    others = aliased(WorkspaceMembership)
    member_count = (
        select(func.count()).where(others.workspace_id == Workspace.workspace_id).scalar_subquery()
    )
    statement = (
        select(Workspace, WorkspaceMembership.role, member_count)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.workspace_id)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(Workspace.created_at, Workspace.workspace_id)
    )
    if workspace_id is not None:
        statement = statement.where(Workspace.workspace_id == workspace_id)
    rows = await db.execute(statement)
    return [
        WorkspaceRead(
            id=workspace.workspace_id,
            name=workspace.name,
            is_personal=workspace.is_personal,
            my_role=role,
            member_count=count,
            # No provider configuration is stored yet, so every workspace uses the built-in model.
            notes_provider=Provider.WHADIO,
            created_at=workspace.created_at,
            default_preset=workspace.default_preset,
        )
        for workspace, role, count in rows
    ]


@router.get(
    "/workspaces",
    summary="List my workspaces",
    description="Workspaces the caller belongs to, oldest first, the personal one included.",
    response_description="A page of workspaces",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def list_workspaces(
    query: Annotated[PageQuery, Query()], user: BrowserUser, db: Db
) -> Page[WorkspaceSummary]:
    workspaces: list[WorkspaceSummary] = [*await _my_workspaces(db, user)]
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
    payload: WorkspaceCreate, user: BrowserUser, request: Request, response: Response, db: Db
) -> WorkspaceRead:
    now = datetime.now(UTC)
    workspace = Workspace(
        name=payload.name,
        default_preset=payload.default_preset,
        is_personal=False,
        created_at=now,
    )
    db.add(workspace)
    await db.flush()
    db.add_all(
        [
            WorkspaceMembership(
                workspace_id=workspace.workspace_id, user_id=user.id, role=Role.OWNER, joined_at=now
            ),
            Folder(
                workspace_id=workspace.workspace_id, name="Default", created_at=now, is_default=True
            ),
        ]
    )
    await db.commit()
    response.headers["Location"] = str(
        request.url_for("get_workspace", workspace_id=workspace.workspace_id)
    )
    return WorkspaceRead(
        id=workspace.workspace_id,
        name=workspace.name,
        is_personal=False,
        my_role=Role.OWNER,
        member_count=1,
        notes_provider=Provider.WHADIO,
        created_at=now,
        default_preset=workspace.default_preset,
    )


@router.get(
    "/workspaces/{workspace_id}",
    summary="Get a workspace",
    description="Any member. Includes the caller's role and where notes are generated.",
    response_description="The workspace",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 404: _NOT_FOUND, 422: DOC_INVALID}),
)
async def get_workspace(workspace_id: WorkspaceId, user: BrowserUser, db: Db) -> WorkspaceRead:
    found = await _my_workspaces(db, user, workspace_id)
    if not found:
        raise not_found("Workspace")
    return found[0]


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
    workspace_id: WorkspaceId, payload: WorkspaceUpdate, user: BrowserUser, db: Db
) -> WorkspaceRead:
    found = await _my_workspaces(db, user, workspace_id)
    if not found:
        raise not_found("Workspace")
    if found[0].my_role is not Role.OWNER:
        raise ApiError(403, ErrorCode.INSUFFICIENT_ROLE, "Only the Owner can change the workspace")
    workspace = await db.get_one(Workspace, workspace_id)
    if payload.name is not None:
        workspace.name = payload.name
    if payload.default_preset is not None:
        workspace.default_preset = payload.default_preset
    await db.commit()
    return found[0].model_copy(
        update={"name": workspace.name, "default_preset": workspace.default_preset}
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
async def delete_workspace(workspace_id: WorkspaceId, user: BrowserUser, db: Db) -> None:
    found = await _my_workspaces(db, user, workspace_id)
    if not found:
        raise not_found("Workspace")
    if found[0].my_role is not Role.OWNER:
        raise ApiError(403, ErrorCode.INSUFFICIENT_ROLE, "Only the Owner can delete the workspace")
    if found[0].is_personal:
        raise ApiError(409, ErrorCode.PERSONAL_WORKSPACE, "A personal workspace cannot be deleted")
    folders = select(Folder.folder_id).where(Folder.workspace_id == workspace_id)
    # Recordings, transcripts and notes are not stored yet; once they are, they go here too.
    await db.execute(delete(Meeting).where(Meeting.folder_id.in_(folders)))
    await db.execute(delete(Folder).where(Folder.workspace_id == workspace_id))
    await db.execute(
        delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
    )
    await db.execute(delete(Workspace).where(Workspace.workspace_id == workspace_id))
    # Same transaction as the deletion (ADR-005), so there is never one without the other.
    db.add(
        AuditEvent(
            occurred_at=datetime.now(UTC),
            actor_user_id=user.id,
            action=AuditAction.WORKSPACE_DELETED,
            workspace_id=workspace_id,
        )
    )
    await db.commit()
