from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...access_policy.models import MeetingAccessGrant
from ...accounts.enums import WorkspaceRole
from ...accounts.models import User, WorkspaceMembership
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ...meetings.enums import AccessMode
from ...meetings.models import Folder, Meeting
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import InvitationCreated, MemberRead, WorkspaceRead

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


def test_members_are_listed_with_their_stored_joining_times(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[dict[UUID, datetime], dict[UUID, datetime]]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            await _join(session, workspace, WorkspaceRole.MODERATOR, 1)
            stored = await session.execute(
                select(WorkspaceMembership.user_id, WorkspaceMembership.joined_at).where(
                    WorkspaceMembership.workspace_id == workspace
                )
            )
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace}/members")
            listed = Page[MemberRead].model_validate_json(response.content).items
            return {item.user_id: item.joined_at for item in listed}, dict(stored.all())

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


async def _restricted_to(
    session: AsyncSession, workspace_id: UUID, owner: User, *recipients: User
) -> UUID:
    folder = await session.scalar(
        select(Folder.folder_id).where(Folder.workspace_id == workspace_id, Folder.is_default)
    )
    assert folder is not None
    meeting = await AsyncDatabase.add_meeting(
        session, (owner.user_id, folder), access_mode=AccessMode.RESTRICTED
    )
    session.add_all(
        MeetingAccessGrant(
            meeting_id=meeting, user_id=user.user_id, granted_by_user_id=owner.user_id
        )
        for user in recipients
    )
    await session.flush()
    return meeting


async def _access(session: AsyncSession, meeting: UUID) -> tuple[AccessMode | None, set[UUID]]:
    mode = await session.scalar(select(Meeting.access_mode).where(Meeting.meeting_id == meeting))
    granted = await session.scalars(
        select(MeetingAccessGrant.user_id).where(MeetingAccessGrant.meeting_id == meeting)
    )
    return mode, set(granted)


def test_removed_member_loses_the_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            # Act
            removed = await client.delete(
                f"/api/v1/workspaces/{workspace}/members/{member.user_id}"
            )
            await _sign_in(client, member)
            opened = await client.get(f"/api/v1/workspaces/{workspace}")
            return removed.status_code, opened.status_code

    # Assert
    assert async_database.run(scenario) == (204, 404)


def test_removal_is_audited_with_the_members_role(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, object]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            moderator = await _join(session, workspace, WorkspaceRole.MODERATOR, 1)
            # Act
            await client.delete(f"/api/v1/workspaces/{workspace}/members/{moderator.user_id}")
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace,
                    AuditEvent.action == AuditAction.MEMBER_REMOVED,
                )
            )
            return (
                None if event is None else (event.actor_user_id, event.subject_id, event.details),
                (owner.user_id, moderator.user_id, {"role": "Moderator"}),
            )

    recorded, expected = async_database.run(scenario)

    # Assert
    assert recorded == expected


def test_removal_drops_the_grant_and_keeps_the_meeting_restricted_for_the_others(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, object]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            colleague = await _join(session, workspace, WorkspaceRole.MEMBER, 2)
            meeting = await _restricted_to(session, workspace, owner, member, colleague)
            # Act
            await client.delete(f"/api/v1/workspaces/{workspace}/members/{member.user_id}")
            return await _access(session, meeting), (AccessMode.RESTRICTED, {colleague.user_id})

    found, expected = async_database.run(scenario)

    # Assert
    assert found == expected


def test_removal_keeps_the_membership_and_grant_in_another_workspace(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(
        session: AsyncSession,
    ) -> tuple[int, WorkspaceRole | None, tuple[AccessMode | None, set[UUID]], UUID]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            created = await client.post("/api/v1/workspaces", json={"name": "Design team"})
            other = WorkspaceRead.model_validate_json(created.content).id
            session.add(
                WorkspaceMembership(
                    workspace_id=other, user_id=member.user_id, role=WorkspaceRole.MEMBER
                )
            )
            meeting = await _restricted_to(session, other, owner, member)
            # Act
            removed = await client.delete(
                f"/api/v1/workspaces/{workspace}/members/{member.user_id}"
            )
            kept = await session.scalar(
                select(WorkspaceMembership.role).where(
                    WorkspaceMembership.workspace_id == other,
                    WorkspaceMembership.user_id == member.user_id,
                )
            )
            return removed.status_code, kept, await _access(session, meeting), member.user_id

    status, role, access, member_id = async_database.run(scenario)

    # Assert
    assert (status, role, access) == (
        204,
        WorkspaceRole.MEMBER,
        (AccessMode.RESTRICTED, {member_id}),
    )


def test_removing_the_last_recipient_is_refused_and_opens_nothing(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, object]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            member = await _join(session, workspace, WorkspaceRole.MEMBER, 1)
            meeting = await _restricted_to(session, workspace, owner, member)
            # Act
            response = await client.delete(
                f"/api/v1/workspaces/{workspace}/members/{member.user_id}"
            )
            listed = Page[MemberRead].model_validate_json(
                (await client.get(f"/api/v1/workspaces/{workspace}/members")).content
            )
            return (
                (response.status_code, _error(response.content)),
                member.user_id in {item.user_id for item in listed.items},
                await _access(session, meeting),
            ), (
                (409, "RESTRICTED_MEETING_REQUIRES_RECIPIENT"),
                True,
                (AccessMode.RESTRICTED, {member.user_id}),
            )

    found, expected = async_database.run(scenario)

    # Assert
    assert found == expected


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        pytest.param("outsider-caller", (404, "NOT_FOUND"), id="outsider-caller"),
        pytest.param("member-caller", (403, "INSUFFICIENT_ROLE"), id="member-caller"),
        pytest.param("owner-target", (409, "OWNER_IMMUTABLE"), id="owner-target"),
        pytest.param("outsider-target", (404, "NOT_FOUND"), id="outsider-target"),
    ],
)
def test_removal_is_refused(
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
            # Act
            response = await client.delete(
                f"/api/v1/workspaces/{workspace}/members/{target.user_id}"
            )
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == refusal


def test_removed_moderators_invitation_link_is_refused(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/team")

    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            moderator = await _join(session, workspace, WorkspaceRole.MODERATOR, 1)
            invitee = await AsyncDatabase.add_account(session, PASSWORD)
            await _sign_in(client, moderator)
            created = InvitationCreated.model_validate_json(
                (
                    await client.post(
                        f"/api/v1/workspaces/{workspace}/invitations",
                        json={"email": invitee.email, "role": "member"},
                    )
                ).content
            )
            assert created.link is not None
            await _sign_in(client, owner)
            await client.delete(f"/api/v1/workspaces/{workspace}/members/{moderator.user_id}")
            await _sign_in(client, invitee)
            # Act
            response = await client.post(
                f"/api/v1/invitations/{created.id}/accept",
                json={"token": urlsplit(created.link).fragment.removeprefix("token=")},
            )
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (404, "LINK_INVALID")
