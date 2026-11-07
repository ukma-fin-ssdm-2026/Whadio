import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .enums import WorkspaceRole
from .member_repository import WorkspaceMember
from .members import MemberService

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


class Members:
    def __init__(self, *members: WorkspaceMember) -> None:
        self.members: list[WorkspaceMember] = list(members)

    async def page(self, workspace_id: UUID, page: ListWindow) -> list[WorkspaceMember]:
        del workspace_id, page
        return self.members


class Memberships:
    def __init__(self, role: WorkspaceRole | None) -> None:
        self.role_value: WorkspaceRole | None = role

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value


def test_outsider_is_told_the_member_list_is_missing() -> None:
    # Arrange
    service = MemberService(Members(), Memberships(None))

    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(service.list(uuid4(), uuid4(), ListWindow(21)))

    # Assert
    assert failure.value.code is Failure.NOT_FOUND


def test_plain_member_lists_the_members() -> None:
    # Arrange
    member = WorkspaceMember(uuid4(), "Bob", "bob@example.com", WorkspaceRole.MEMBER, NOW)
    service = MemberService(Members(member), Memberships(WorkspaceRole.MEMBER))

    # Act
    found = asyncio.run(service.list(uuid4(), uuid4(), ListWindow(21)))

    # Assert
    assert found == [member]
