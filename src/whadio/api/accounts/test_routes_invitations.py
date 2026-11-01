import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import InvitationRole, InvitationStatus, WorkspaceRole
from ...accounts.models import Invitation, User, Workspace, WorkspaceMembership
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import InvitationCreated, InvitationRead, WorkspaceRead

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


@pytest.fixture(autouse=True)
def public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/team")


async def _owner_workspace(client: AsyncClient, session: AsyncSession) -> tuple[UUID, UUID]:
    owner = await AsyncDatabase.add_account(session, PASSWORD)
    await client.post("/api/v1/sessions", json={"email": owner.email, "password": PASSWORD})
    response = await client.post("/api/v1/workspaces", json={"name": "Product team"})
    return owner.user_id, WorkspaceRead.model_validate_json(response.content).id


def _error(response_text: bytes) -> str:
    return ErrorResponse.model_validate_json(response_text).error.code


def test_reissuing_invitation_replaces_secret_and_preserves_id(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, ...]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace_id = await _owner_workspace(client, session)
            first = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                json={"email": "New@Example.com", "role": "member"},
            )
            # Act
            second = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                json={"email": "new@example.com", "role": "moderator"},
            )
            first_body = InvitationCreated.model_validate_json(first.content)
            second_body = InvitationCreated.model_validate_json(second.content)
            stored = await session.scalar(
                select(Invitation).where(Invitation.workspace_id == workspace_id)
            )
            assert stored is not None
            assert second_body.link is not None
            token = urlsplit(second_body.link).fragment.removeprefix("token=")
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.action == AuditAction.MEMBER_INVITED,
                )
            )
            return (
                first.status_code,
                second.status_code,
                first_body.id == second_body.id,
                first_body.link != second_body.link,
                stored.invited_email,
                stored.role,
                stored.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                audit_count,
            )

    # Assert
    assert async_database.run(scenario) == (
        201,
        200,
        True,
        True,
        "new@example.com",
        InvitationRole.MODERATOR,
        True,
        2,
    )


def test_pending_invitation_can_be_listed_then_cancelled(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[object, ...]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace_id = await _owner_workspace(client, session)
            created = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                json={"email": "new@example.com", "role": "member"},
            )
            invitation_id = InvitationCreated.model_validate_json(created.content).id
            listed = await client.get(f"/api/v1/workspaces/{workspace_id}/invitations")
            # Act
            cancelled = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel"
            )
            repeated = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel"
            )
            listed_after = await client.get(f"/api/v1/workspaces/{workspace_id}/invitations")
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.action == AuditAction.INVITATION_CANCELLED,
                )
            )
            listed_page = Page[InvitationRead].model_validate_json(listed.content)
            listed_after_page = Page[InvitationRead].model_validate_json(listed_after.content)
            listed_item = listed_page.items[0]
            return (
                '"link"' not in listed.text and '"token"' not in listed.text,
                listed_item.link_active,
                cancelled.status_code,
                InvitationRead.model_validate_json(cancelled.content).status,
                repeated.status_code,
                _error(repeated.content),
                listed_after_page.items,
                audit_count,
            )

    # Assert
    assert async_database.run(scenario) == (
        True,
        True,
        200,
        "cancelled",
        409,
        "INVITATION_NOT_PENDING",
        [],
        1,
    )


def test_member_cannot_manage_invitations(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace_id = await _owner_workspace(client, session)
            member = await AsyncDatabase.add_account(session, PASSWORD)
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace_id,
                    user_id=member.user_id,
                    role=WorkspaceRole.MEMBER,
                )
            )
            await session.flush()
            await client.delete("/api/v1/sessions/current")
            await client.post(
                "/api/v1/sessions", json={"email": member.email, "password": PASSWORD}
            )
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace_id}/invitations")
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (403, "INSUFFICIENT_ROLE")


def test_personal_workspace_rejects_invitations(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace_id = await _owner_workspace(client, session)
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            workspace.is_personal = True
            await session.flush()
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                json={"email": "new@example.com", "role": "member"},
            )
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (409, "PERSONAL_WORKSPACE")


def test_daily_invitation_limit_returns_retry_after(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str, bool]:
        async with AsyncDatabase.api_client(session) as client:
            owner_id, workspace_id = await _owner_workspace(client, session)
            now = datetime.now(UTC)
            session.add_all(
                [
                    Invitation(
                        workspace_id=workspace_id,
                        invited_email=f"invitee-{index}@example.com",
                        role=InvitationRole.MEMBER,
                        invited_by_user_id=owner_id,
                        status=InvitationStatus.CANCELLED,
                        token_hash=uuid4().hex,
                        created_at=now - timedelta(minutes=index),
                        expires_at=now + timedelta(days=7),
                        responded_at=now,
                    )
                    for index in range(20)
                ]
            )
            await session.flush()
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                json={"email": "last@example.com", "role": "member"},
            )
            return response.status_code, _error(response.content), "Retry-After" in response.headers

    # Assert
    assert async_database.run(scenario) == (429, "INVITATION_LIMIT", True)


@pytest.mark.parametrize("action", ["list", "create", "cancel"])
@pytest.mark.parametrize("role", [WorkspaceRole.MEMBER, None])
def test_management_refuses_members_and_outsiders(
    async_database: AsyncDatabase, action: str, role: WorkspaceRole | None
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            created = await client.post(
                f"/api/v1/workspaces/{workspace}/invitations",
                json={"email": "new@example.com", "role": "member"},
            )
            invitation = InvitationCreated.model_validate_json(created.content)
            actor = await AsyncDatabase.add_account(session, PASSWORD)
            if role is not None:
                session.add(
                    WorkspaceMembership(workspace_id=workspace, user_id=actor.user_id, role=role)
                )
                await session.flush()
            await client.post("/api/v1/sessions", json={"email": actor.email, "password": PASSWORD})
            path = f"/api/v1/workspaces/{workspace}/invitations"
            # Act
            if action == "list":
                response = await client.get(path)
            elif action == "create":
                response = await client.post(
                    path, json={"email": "other@example.com", "role": "member"}
                )
            else:
                response = await client.post(f"{path}/{invitation.id}/cancel")
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (
        (403, "INSUFFICIENT_ROLE") if role is not None else (404, "NOT_FOUND")
    )


def test_existing_member_is_refused_case_insensitively(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            account = await session.get(User, owner)
            assert account is not None
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{workspace}/invitations",
                json={"email": account.email.upper(), "role": "member"},
            )
            return response.status_code, _error(response.content)

    # Assert
    assert async_database.run(scenario) == (409, "ALREADY_MEMBER")


def test_cancellation_is_scoped_to_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str, InvitationStatus]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            created = await client.post(
                f"/api/v1/workspaces/{workspace}/invitations",
                json={"email": "new@example.com", "role": "member"},
            )
            invitation = InvitationCreated.model_validate_json(created.content)
            other = await client.post("/api/v1/workspaces", json={"name": "Other"})
            other_id = WorkspaceRead.model_validate_json(other.content).id
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{other_id}/invitations/{invitation.id}/cancel"
            )
            stored = await session.get(Invitation, invitation.id)
            assert stored is not None
            return response.status_code, _error(response.content), stored.status

    # Assert
    assert async_database.run(scenario) == (404, "NOT_FOUND", InvitationStatus.PENDING)


def test_missing_public_url_refuses_without_writes(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")

    async def scenario(session: AsyncSession) -> tuple[int, str, int | None]:
        async with AsyncDatabase.api_client(session) as client:
            _, workspace = await _owner_workspace(client, session)
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{workspace}/invitations",
                json={"email": "new@example.com", "role": "member"},
            )
            count = await session.scalar(
                select(func.count())
                .select_from(Invitation)
                .where(Invitation.workspace_id == workspace)
            )
            return response.status_code, _error(response.content), count

    # Assert
    assert async_database.run(scenario) == (503, "INTEGRATION_UNAVAILABLE", 0)


def test_pagination_and_moderator_management(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool, int, int, int]:
        async with AsyncDatabase.api_client(session) as client:
            owner, workspace = await _owner_workspace(client, session)
            now = datetime.now(UTC)
            session.add_all(
                [
                    Invitation(
                        workspace_id=workspace,
                        invited_email=f"page-{i}@example.com",
                        role=InvitationRole.MEMBER,
                        invited_by_user_id=owner,
                        status=InvitationStatus.PENDING,
                        token_hash=uuid4().hex,
                        created_at=now,
                        expires_at=now + timedelta(days=7),
                    )
                    for i in range(3)
                ]
            )
            await session.flush()
            path = f"/api/v1/workspaces/{workspace}/invitations"
            first = Page[InvitationRead].model_validate_json(
                (await client.get(path, params={"limit": 1})).content
            )
            assert first.pagination.next_cursor is not None
            second = Page[InvitationRead].model_validate_json(
                (
                    await client.get(
                        path, params={"limit": 1, "cursor": first.pagination.next_cursor}
                    )
                ).content
            )
            moderator = await AsyncDatabase.add_account(session, PASSWORD)
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace, user_id=moderator.user_id, role=WorkspaceRole.MODERATOR
                )
            )
            await session.flush()
            await client.post(
                "/api/v1/sessions", json={"email": moderator.email, "password": PASSWORD}
            )
            # Act
            reused = await client.get(path, params={"cursor": first.pagination.next_cursor})
            created = await client.post(
                path, json={"email": "moderator-invite@example.com", "role": "moderator"}
            )
            invitation = InvitationCreated.model_validate_json(created.content)
            cancelled = await client.post(f"{path}/{invitation.id}/cancel")
            return (
                first.items[0].id != second.items[0].id,
                invitation.link is not None
                and invitation.link.startswith("https://example.com/team/invitations/"),
                reused.status_code,
                created.status_code,
                cancelled.status_code,
            )

    # Assert
    assert async_database.run(scenario) == (True, True, 422, 201, 200)
