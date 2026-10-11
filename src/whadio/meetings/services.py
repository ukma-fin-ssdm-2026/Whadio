from datetime import datetime
from uuid import UUID

from ..accounts.enums import WorkspaceRole
from ..accounts.services import IWorkspaceMembership
from ..audit.services import IAuditWriter, MeetingMoved
from ..shared.errors import Failure, UseCaseError
from .repositories import IFolderRepository


class FolderService:
    def __init__(
        self,
        repository: IFolderRepository,
        memberships: IWorkspaceMembership,
        audit: IAuditWriter,
    ) -> None:
        self._repository: IFolderRepository = repository
        self._memberships: IWorkspaceMembership = memberships
        self._audit: IAuditWriter = audit

    async def delete_folder(
        self, actor_id: UUID, workspace_id: UUID, folder_id: UUID, now: datetime
    ) -> None:
        """Move, audit and delete using collaborators sharing the caller's transaction."""
        role = await self._memberships.lock_role(workspace_id, actor_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        folder = await self._repository.folder(workspace_id, folder_id)
        if folder is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if folder.is_default:
            raise UseCaseError(Failure.DEFAULT_FOLDER)
        destination = await self._repository.default_folder(workspace_id)
        if destination is None:
            raise UseCaseError(Failure.NOT_FOUND)
        for meeting_id in await self._repository.move_meetings(folder_id, destination.folder_id):
            await self._audit.write(
                MeetingMoved(
                    actor_id,
                    workspace_id,
                    meeting_id,
                    now,
                    folder_id,
                    destination.folder_id,
                )
            )
        await self._repository.remove_folder(folder_id)
