from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import WorkspaceRole
from ...accounts.models import User, WorkspaceMembership
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
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


def test_moderator_promotion_is_applied_and_audited(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, ...]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            moderator = await _join(session, workspace, WorkspaceRole.MODERATOR, 1)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 2)
            await _sign_in(client, moderator)
            # Act
            response = await client.patch(
                f"/api/v1/workspaces/{workspace}/members/{member.user_id}",
                json={"role": "moderator"},
            )
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace,
                    AuditEvent.action == AuditAction.MEMBER_ROLE_CHANGED,
                )
            )
            return (
                response.status_code,
                MemberRead.model_validate_json(response.content).role.value,
                None if event is None else (event.actor_user_id, event.subject_id, event.details),
                (
                    moderator.user_id,
                    member.user_id,
                    {"from_role": "Member", "to_role": "Moderator"},
                ),
            )

    status, role, recorded, expected = async_database.run(scenario)

    # Assert
    assert (status, role, recorded) == (200, "moderator", expected)


def test_demoted_moderator_is_refused_on_their_next_request(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            moderator = await _join(session, workspace, WorkspaceRole.MODERATOR, 1)
            await client.patch(
                f"/api/v1/workspaces/{workspace}/members/{moderator.user_id}",
                json={"role": "member"},
            )
            await _sign_in(client, moderator)
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace}/invitations")
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (403, "INSUFFICIENT_ROLE")


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        pytest.param("outsider-caller", (404, "NOT_FOUND"), id="outsider-caller"),
        pytest.param("member-caller", (403, "INSUFFICIENT_ROLE"), id="member-caller"),
        pytest.param("owner-target", (409, "OWNER_IMMUTABLE"), id="owner-target"),
        pytest.param("outsider-target", (404, "NOT_FOUND"), id="outsider-target"),
        pytest.param("owner-role", (422, "VALIDATION_ERROR"), id="owner-role"),
    ],
)
def test_role_change_is_refused(
    async_database: AsyncDatabase, case: str, refusal: tuple[int, str]
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            target = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            if case == "outsider-caller":
                await _sign_in(client, await AsyncDatabase.add_account(session, PASSWORD))
            elif case == "member-caller":
                await _sign_in(client, await _join(session, workspace, WorkspaceRole.MEMBER, 2))
            elif case == "owner-target":
                target = owner
            elif case == "outsider-target":
                target = await AsyncDatabase.add_account(session, PASSWORD)
            role = "owner" if case == "owner-role" else "moderator"
            # Act
            response = await client.patch(
                f"/api/v1/workspaces/{workspace}/members/{target.user_id}", json={"role": role}
            )
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == refusal
