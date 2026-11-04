from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import WorkspaceRole
from ...accounts.models import User, WorkspaceMembership
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import MemberRead, WorkspaceRead

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


async def _owner_workspace(client: AsyncClient, session: AsyncSession) -> tuple[User, UUID]:
    owner = await AsyncDatabase.add_account(session, PASSWORD, name="Olena")
    await _sign_in(client, owner)
    response = await client.post("/api/v1/workspaces", json={"name": "Product team"})
    return owner, WorkspaceRead.model_validate_json(response.content).id


async def _sign_in(client: AsyncClient, user: User) -> None:
    await client.post("/api/v1/sessions", json={"email": user.email, "password": PASSWORD})


async def _join(
    session: AsyncSession, workspace_id: UUID, role: WorkspaceRole, minutes: int, name: str = "Bob"
) -> User:
    member = await AsyncDatabase.add_account(session, PASSWORD, name=name)
    session.add(
        WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=member.user_id,
            role=role,
            joined_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    await session.flush()
    return member


def _error(response: bytes) -> str:
    return ErrorResponse.model_validate_json(response).error.code


def test_members_are_listed_with_their_roles_oldest_first(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(
        session: AsyncSession,
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 2, "Bohdan")
            moderator = await _join(session, workspace, WorkspaceRole.MODERATOR, 1, "Mariia")
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace}/members")
            found = Page[MemberRead].model_validate_json(response.content).items
            return [(item.name, item.email, item.role.value) for item in found], [
                (owner.name, owner.email, "owner"),
                (moderator.name, moderator.email, "moderator"),
                (member.name, member.email, "member"),
            ]

    found, expected = async_database.run(scenario)

    # Assert
    assert found == expected


def test_member_list_continues_on_the_next_page(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], list[UUID], bool]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            joined = [
                (await _join(session, workspace, WorkspaceRole.MEMBER, minutes)).user_id
                for minutes in (1, 2)
            ]
            path = f"/api/v1/workspaces/{workspace}/members"
            first = Page[MemberRead].model_validate_json(
                (await client.get(path, params={"limit": 2})).content
            )
            # Act
            second = Page[MemberRead].model_validate_json(
                (
                    await client.get(
                        path, params={"limit": 2, "cursor": first.pagination.next_cursor}
                    )
                ).content
            )
            return (
                [item.user_id for item in first.items + second.items],
                [owner.user_id, *joined],
                second.pagination.has_more,
            )

    found, expected, has_more = async_database.run(scenario)

    # Assert
    assert (found, has_more) == (expected, False)


def test_outsider_is_told_the_member_list_is_missing(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            await _sign_in(client, await AsyncDatabase.add_account(session, PASSWORD))
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace}/members")
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (404, "NOT_FOUND")


def test_cursor_of_another_caller_is_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            await _join(session, workspace, WorkspaceRole.MEMBER, 2)
            path = f"/api/v1/workspaces/{workspace}/members"
            first = Page[MemberRead].model_validate_json(
                (await client.get(path, params={"limit": 1})).content
            )
            await _sign_in(client, member)
            # Act
            response = await client.get(path, params={"cursor": first.pagination.next_cursor})
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (422, "VALIDATION_ERROR")
