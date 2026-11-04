from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..shared.pagination import ListCursor, ListWindow
from .enums import NotesTemplate, WorkspaceRole
from .member_repository import MemberRepository, WorkspaceMember
from .models import User, Workspace, WorkspaceMembership

pytestmark = pytest.mark.slow

JOINED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


async def add_workspace(session: AsyncSession) -> UUID:
    workspace = Workspace(name="Team", default_template=NotesTemplate.SUMMARY)
    session.add(workspace)
    await session.flush()
    return workspace.workspace_id


async def add_member(
    session: AsyncSession,
    workspace_id: UUID,
    joined_at: datetime,
    user_id: UUID | None = None,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> WorkspaceMember:
    user = User(
        user_id=user_id or uuid4(),
        email=f"{uuid4()}@example.com",
        name="Bob",
        password_hash=uuid4().hex,
        terms_accepted_at=JOINED,
    )
    session.add(user)
    await session.flush()
    session.add(
        WorkspaceMembership(
            workspace_id=workspace_id, user_id=user.user_id, role=role, joined_at=joined_at
        )
    )
    await session.flush()
    return WorkspaceMember(user.user_id, user.name, user.email, role, joined_at)


def test_members_who_joined_together_are_ordered_by_user_id(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    first, second = sorted([uuid4(), uuid4()])

    async def scenario(session: AsyncSession) -> list[UUID]:
        workspace = await add_workspace(session)
        await add_member(session, workspace, JOINED, second)
        await add_member(session, workspace, JOINED, first)
        # Act
        return [
            item.user_id for item in await MemberRepository(session).page(workspace, ListWindow(21))
        ]

    # Assert
    assert async_database.run(scenario) == [first, second]


def test_page_after_a_cursor_starts_past_its_member(async_database: AsyncDatabase) -> None:
    # Arrange
    first, second = sorted([uuid4(), uuid4()])

    async def scenario(session: AsyncSession) -> tuple[list[UUID], list[UUID]]:
        workspace = await add_workspace(session)
        await add_member(session, workspace, JOINED, first)
        tied = await add_member(session, workspace, JOINED, second)
        later = await add_member(session, workspace, JOINED + timedelta(minutes=1))
        cursor = ListCursor(JOINED.isoformat(), first)
        # Act
        found = await MemberRepository(session).page(workspace, ListWindow(21, cursor))
        return [item.user_id for item in found], [tied.user_id, later.user_id]

    found, expected = async_database.run(scenario)

    # Assert
    assert found == expected


def test_page_holds_at_most_its_limit(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        workspace = await add_workspace(session)
        for minute in range(3):
            await add_member(session, workspace, JOINED + timedelta(minutes=minute))
        # Act
        return len(await MemberRepository(session).page(workspace, ListWindow(2)))

    # Assert
    assert async_database.run(scenario) == 2


def test_members_of_another_workspace_are_left_out(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[WorkspaceMember]:
        workspace = await add_workspace(session)
        await add_member(session, await add_workspace(session), JOINED)
        # Act
        return await MemberRepository(session).page(workspace, ListWindow(21))

    # Assert
    assert async_database.run(scenario) == []


def test_new_role_is_stored_for_that_member_only(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[WorkspaceRole]:
        workspace = await add_workspace(session)
        target = await add_member(session, workspace, JOINED)
        await add_member(session, workspace, JOINED + timedelta(minutes=1))
        repository = MemberRepository(session)
        # Act
        await repository.set_role(workspace, target.user_id, WorkspaceRole.MODERATOR)
        return [item.role for item in await repository.page(workspace, ListWindow(21))]

    # Assert
    assert async_database.run(scenario) == [WorkspaceRole.MODERATOR, WorkspaceRole.MEMBER]
