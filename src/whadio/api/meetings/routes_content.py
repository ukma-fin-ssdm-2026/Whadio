from datetime import UTC, datetime
from typing import Annotated, Self
from uuid import UUID, uuid4

from fastapi import APIRouter, Path, Query, Response
from pydantic import Field, model_validator

from ...meetings.models import Folder, GlossaryTerm
from ...meetings.services import TermUpdate, TranscriptEdit
from ...shared.pagination import ListCursor
from ..accounts.auth import BrowserUser
from ..accounts.schemas import WorkspaceId
from ..composition import Folders, Meetings
from ..core.errors import error_responses
from ..core.pagination import list_page, list_window
from ..core.schemas import DisplayText, Input, Output, Page, PageQuery
from .schemas import FolderId, MeetingId, RevisionRead, RevisionType, TranscriptRead
from .views import transcript_read

TermId = Annotated[UUID, Path(description="Glossary term identifier")]

router = APIRouter(
    tags=["meetings"],
    responses=error_responses(
        {
            401: "Authentication required",
            403: "Insufficient role",
            404: "Not found or not visible",
            409: "Content conflict",
            422: "Invalid input",
        }
    ),
)


class FolderInput(Input):
    name: DisplayText = Field(min_length=1, max_length=100, description="Folder name")


class FolderRead(Output):
    id: UUID = Field(description="Folder identifier")
    name: str = Field(description="Folder name")
    is_default: bool = Field(description="Whether the folder receives unfiled meetings")
    meeting_count: int = Field(description="Number of meetings the caller can read")


async def _folder_read(folder: Folder, user: BrowserUser, service: Meetings) -> FolderRead:
    count = await service.folder_count(user.id, folder.workspace_id, folder.folder_id)
    return FolderRead(
        id=folder.folder_id,
        name=folder.name,
        is_default=folder.is_default,
        meeting_count=count,
    )


@router.get(
    "/workspaces/{workspace_id}/folders",
    description=(
        "List workspace folders with counts of meetings the caller can read. "
        "Restricted meetings without access are excluded from counts."
    ),
)
async def list_folders(
    workspace_id: WorkspaceId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    service: Meetings,
) -> Page[FolderRead]:
    scope = f"folders:{workspace_id}:{user.id}"
    folders = await service.folders(user.id, workspace_id, list_window(query, scope))
    last = folders[min(len(folders), query.limit) - 1] if folders else None
    cursor = (
        None
        if last is None
        else ListCursor(("0:" if last.is_default else "1:") + last.name.lower(), last.folder_id)
    )
    counts = await service.folder_counts(
        user.id, workspace_id, [folder.folder_id for folder in folders]
    )
    return list_page(
        [
            FolderRead(
                id=folder.folder_id,
                name=folder.name,
                is_default=folder.is_default,
                meeting_count=counts.get(folder.folder_id, 0),
            )
            for folder in folders
        ],
        query,
        scope,
        cursor,
    )


@router.post(
    "/workspaces/{workspace_id}/folders",
    status_code=201,
    description=(
        "Create a folder in this workspace. Requires a Moderator or Owner; "
        "names are unique ignoring case."
    ),
)
async def create_folder(
    workspace_id: WorkspaceId,
    payload: FolderInput,
    user: BrowserUser,
    service: Meetings,
    response: Response,
) -> FolderRead:
    folder = await service.create_folder(user.id, workspace_id, payload.name, datetime.now(UTC))
    response.headers["Location"] = f"/api/v1/workspaces/{workspace_id}/folders/{folder.folder_id}"
    return await _folder_read(folder, user, service)


@router.patch(
    "/workspaces/{workspace_id}/folders/{folder_id}",
    description=(
        "Rename a workspace folder. Requires a Moderator or Owner and a name "
        "unique within the workspace."
    ),
)
async def rename_folder(
    workspace_id: WorkspaceId,
    folder_id: FolderId,
    payload: FolderInput,
    user: BrowserUser,
    service: Meetings,
) -> FolderRead:
    return await _folder_read(
        await service.rename_folder(user.id, workspace_id, folder_id, payload.name), user, service
    )


@router.delete(
    "/workspaces/{workspace_id}/folders/{folder_id}",
    status_code=204,
    description=(
        "Delete a non-default folder and move its meetings to the default "
        "folder, preserving their content and access restrictions. Requires a "
        "Moderator or Owner."
    ),
)
async def delete_folder(
    workspace_id: WorkspaceId, folder_id: FolderId, user: BrowserUser, service: Folders
) -> None:
    await service.delete_folder(user.id, workspace_id, folder_id, datetime.now(UTC))


@router.post(
    "/workspaces/{workspace_id}/folders/{folder_id}/restore",
    description=(
        "Restore a deleted folder and its previous meeting placement. Requires "
        "a Moderator or Owner; refuses to overwrite later moves."
    ),
)
async def restore_folder(
    workspace_id: WorkspaceId,
    folder_id: FolderId,
    user: BrowserUser,
    folders: Folders,
    meetings: Meetings,
) -> FolderRead:
    folder = await folders.restore_folder(user.id, workspace_id, folder_id, datetime.now(UTC))
    return await _folder_read(folder, user, meetings)


class SegmentCorrection(Input):
    id: UUID = Field(description="Segment of the base revision")
    text: str = Field(description="Corrected text")


class SpeakerRename(Input):
    id: UUID = Field(description="Speaker of the base revision")
    display_name: DisplayText = Field(min_length=1, max_length=200, description="Corrected label")


class RevisionInput(Input):
    base_revision_id: UUID = Field(description="Current revision the edit is based on")
    segments: list[SegmentCorrection] = Field(default_factory=list, description="Text corrections")
    speakers: list[SpeakerRename] = Field(default_factory=list, description="Speaker label changes")

    @model_validator(mode="after")
    def validate_edit(self) -> Self:
        if not self.segments and not self.speakers:
            raise ValueError("Supply a text correction or speaker rename")
        if len({item.id for item in self.segments}) != len(self.segments) or len(
            {item.id for item in self.speakers}
        ) != len(self.speakers):
            raise ValueError("Each segment and speaker may appear once")
        return self


@router.get(
    "/meetings/{meeting_id}/transcript/revisions",
    description=(
        "List transcript revisions newest first for an accessible meeting, "
        "including original provenance and current revision status."
    ),
)
async def list_revisions(
    meeting_id: MeetingId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    service: Meetings,
) -> Page[RevisionRead]:
    current = await service.transcript(user.id, meeting_id)
    scope = f"revisions:{meeting_id}:{user.id}"
    revisions = await service.revisions(
        user.id, meeting_id, list_window(query, scope, chronological=True)
    )
    last = revisions[min(len(revisions), query.limit) - 1] if revisions else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.revision_id)
    return list_page(
        [
            RevisionRead(
                id=item.revision_id,
                revision_type=RevisionType(item.revision_type),
                created_at=item.created_at,
                edited_by_user_id=item.edited_by_user_id,
                is_current=item.revision_id == current.transcript.current_revision_id,
            )
            for item in revisions
        ],
        query,
        scope,
        cursor,
    )


@router.post(
    "/meetings/{meeting_id}/transcript/revisions",
    status_code=201,
    description=(
        "Create a transcript revision with text corrections or speaker renames. "
        "Requires meeting access and the current base revision; preserves the "
        "original transcript."
    ),
)
async def edit_transcript(
    meeting_id: MeetingId,
    payload: RevisionInput,
    user: BrowserUser,
    service: Meetings,
    response: Response,
) -> TranscriptRead:
    version = await service.edit_transcript(
        user.id,
        meeting_id,
        TranscriptEdit(
            payload.base_revision_id,
            {item.id: item.text for item in payload.segments},
            {item.id: item.display_name for item in payload.speakers},
        ),
        datetime.now(UTC),
    )
    response.headers["Location"] = (
        f"/api/v1/meetings/{meeting_id}/transcript?revision_id={version.revision.revision_id}"
    )
    return transcript_read(version)


class TermInput(Input):
    term: DisplayText = Field(min_length=1, max_length=200, description="Glossary term")
    preferred_form: DisplayText = Field(
        min_length=1, max_length=200, description="Preferred spelling"
    )
    description: str = Field(default="", max_length=2000, description="Explanation")
    source_meeting_id: UUID | None = Field(
        default=None, description="Accessible meeting the term came from"
    )


class TermPatch(Input):
    term: DisplayText | None = Field(
        default=None, min_length=1, max_length=200, description="New term"
    )
    preferred_form: DisplayText | None = Field(
        default=None, min_length=1, max_length=200, description="New spelling"
    )
    description: str | None = Field(default=None, max_length=2000, description="New explanation")

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.term is None and self.preferred_form is None and self.description is None:
            raise ValueError("Supply at least one change")
        return self


class TermRead(Output):
    id: UUID = Field(description="Term identifier")
    term: str = Field(description="Term")
    preferred_form: str = Field(description="Preferred spelling")
    description: str = Field(description="Explanation")
    source_meeting_id: UUID | None = Field(description="Source meeting, if still present")
    created_by_user_id: UUID = Field(description="Author of the term")


def _term_read(term: GlossaryTerm) -> TermRead:
    return TermRead(
        id=term.term_id,
        term=term.term,
        preferred_form=term.preferred_form,
        description=term.description,
        source_meeting_id=term.source_meeting_id,
        created_by_user_id=term.created_by_user_id,
    )


@router.get(
    "/workspaces/{workspace_id}/glossary-terms",
    description="List the workspace glossary for a signed-in workspace member.",
)
async def glossary(
    workspace_id: WorkspaceId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    service: Meetings,
) -> Page[TermRead]:
    scope = f"glossary:{workspace_id}:{user.id}"
    terms = await service.glossary(user.id, workspace_id, list_window(query, scope))
    last = terms[min(len(terms), query.limit) - 1] if terms else None
    cursor = None if last is None else ListCursor(last.term.lower(), last.term_id)
    return list_page([_term_read(item) for item in terms], query, scope, cursor)


@router.post(
    "/workspaces/{workspace_id}/glossary-terms",
    status_code=201,
    description=(
        "Add a workspace glossary term as a member. Terms are unique ignoring "
        "case; any source meeting must be accessible."
    ),
)
async def add_term(
    workspace_id: WorkspaceId,
    payload: TermInput,
    user: BrowserUser,
    service: Meetings,
    response: Response,
) -> TermRead:
    term = GlossaryTerm(
        term_id=uuid4(),
        workspace_id=workspace_id,
        term=payload.term,
        preferred_form=payload.preferred_form,
        description=payload.description,
        source_meeting_id=payload.source_meeting_id,
        created_by_user_id=user.id,
        created_at=datetime.now(UTC),
    )
    created = await service.add_term(user.id, term)
    response.headers["Location"] = (
        f"/api/v1/workspaces/{workspace_id}/glossary-terms/{created.term_id}"
    )
    return _term_read(created)


@router.patch(
    "/workspaces/{workspace_id}/glossary-terms/{term_id}",
    description=(
        "Update a glossary term as its author, a Moderator or the Owner. A "
        "changed term must remain unique ignoring case."
    ),
)
async def update_term(
    workspace_id: WorkspaceId,
    term_id: TermId,
    payload: TermPatch,
    user: BrowserUser,
    service: Meetings,
) -> TermRead:
    return _term_read(
        await service.update_term(
            user.id,
            workspace_id,
            term_id,
            TermUpdate(payload.term, payload.preferred_form, payload.description),
        )
    )


@router.delete(
    "/workspaces/{workspace_id}/glossary-terms/{term_id}",
    status_code=204,
    description="Remove a glossary term as its author, a Moderator or the Owner.",
)
async def delete_term(
    workspace_id: WorkspaceId, term_id: TermId, user: BrowserUser, service: Meetings
) -> None:
    await service.delete_term(user.id, workspace_id, term_id)
