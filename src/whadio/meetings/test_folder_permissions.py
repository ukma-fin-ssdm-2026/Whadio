import asyncio
from datetime import UTC, datetime
from typing import override
from uuid import UUID, uuid4

import pytest

from ..accounts.enums import WorkspaceRole
from ..accounts.services import IWorkspaceMembership
from ..audit.services import IAuditWriter, MeetingMoved
from ..shared.errors import Failure, UseCaseError
from .models import Folder
from .repositories import IFolderRepository
from .services import FolderService


class Memberships(IWorkspaceMembership):
    def __init__(self, role: WorkspaceRole | None) -> None:
        self._role: WorkspaceRole | None = role

    @override
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        raise AssertionError("Folder deletion must lock the acting membership")

    @override
    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return self._role


class Folders(IFolderRepository):
    def __init__(self, folder: Folder | None, destination: Folder | None = None) -> None:
        self._folder: Folder | None = folder
        self._destination: Folder | None = destination

    @override
    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None:
        return self._folder

    @override
    async def default_folder(self, workspace_id: UUID) -> Folder | None:
        return self._destination

    @override
    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]:
        raise AssertionError("Refused deletion must not move meetings")

    @override
    async def remember(self, folder: Folder, meeting_ids: list[UUID], now: datetime) -> None:
        raise AssertionError("Refused deletion must not remember a folder")

    @override
    async def restore(self, workspace_id: UUID, folder_id: UUID) -> tuple[Folder, list[UUID]]:
        raise AssertionError("Refused restoration must not change a folder")

    @override
    async def remove_folder(self, folder_id: UUID) -> None:
        raise AssertionError("Refused deletion must not remove a folder")


class Audit(IAuditWriter):
    @override
    async def write(self, event: MeetingMoved) -> None:
        raise AssertionError("Refused deletion must not write audit events")


def deletion_failure(service: FolderService) -> Failure:
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(service.delete_folder(uuid4(), uuid4(), uuid4(), datetime.now(UTC)))
    return failure.value.code


def test_member_cannot_delete_a_folder() -> None:
    # Arrange
    service = FolderService(Folders(None), Memberships(WorkspaceRole.MEMBER), Audit())
    # Act
    failure = deletion_failure(service)
    # Assert
    assert failure == Failure.INSUFFICIENT_ROLE


def test_outsider_cannot_delete_a_folder() -> None:
    # Arrange
    service = FolderService(Folders(None), Memberships(None), Audit())
    # Act
    failure = deletion_failure(service)
    # Assert
    assert failure == Failure.NOT_FOUND


def test_default_folder_cannot_be_deleted() -> None:
    # Arrange
    folder = Folder(folder_id=uuid4(), workspace_id=uuid4(), name="default", is_default=True)
    service = FolderService(Folders(folder), Memberships(WorkspaceRole.OWNER), Audit())
    # Act
    failure = deletion_failure(service)
    # Assert
    assert failure == Failure.DEFAULT_FOLDER


def test_missing_folder_cannot_be_deleted() -> None:
    # Arrange
    service = FolderService(Folders(None), Memberships(WorkspaceRole.MODERATOR), Audit())
    # Act
    failure = deletion_failure(service)
    # Assert
    assert failure == Failure.NOT_FOUND


def test_folder_deletion_requires_a_default_destination() -> None:
    # Arrange
    folder = Folder(folder_id=uuid4(), workspace_id=uuid4(), name="source", is_default=False)
    service = FolderService(Folders(folder), Memberships(WorkspaceRole.OWNER), Audit())
    # Act
    failure = deletion_failure(service)
    # Assert
    assert failure == Failure.NOT_FOUND
