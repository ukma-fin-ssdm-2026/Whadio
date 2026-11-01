from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import InvitationStatus, WorkspaceRole
from ...accounts.models import Invitation, User, WorkspaceMembership
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ...meetings.models import Folder
from .schemas import InvitationCreated, WorkspaceRead

pytestmark = pytest.mark.slow
PASSWORD = f" A1{uuid4().hex} "


async def issue(client: AsyncClient, session: AsyncSession, email: str) -> tuple[UUID, UUID, str]:
    owner = await AsyncDatabase.add_account(session, PASSWORD)
    await client.post("/api/v1/sessions", json={"email": owner.email, "password": PASSWORD})
    response = await client.post("/api/v1/workspaces", json={"name": "Team"})
    workspace = WorkspaceRead.model_validate_json(response.content)
    response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/invitations", json={"email": email, "role": "moderator"}
    )
    invitation = InvitationCreated.model_validate_json(response.content)
    assert invitation.link is not None
    return owner.user_id, invitation.id, urlsplit(invitation.link).fragment.removeprefix("token=")


def test_register_creates_account_membership_folder_session_and_one_audit(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool, int, int]:
        async with AsyncDatabase.api_client(session) as client:
            email = f"{uuid4()}@example.com"
            _, invitation_id, token = await issue(client, session, email)
            await client.delete("/api/v1/sessions/current")
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/register",
                json={
                    "token": token,
                    "name": "New member",
                    "password": PASSWORD,
                    "accept_terms": True,
                },
            )
            user = await session.scalar(select(User).where(User.email == email))
            assert user is not None
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            memberships = await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.user_id == user.user_id)
            )
            folder = await session.scalar(
                select(Folder.folder_id)
                .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Folder.workspace_id)
                .where(WorkspaceMembership.user_id == user.user_id, Folder.is_default)
            )
            audits = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == user.user_id,
                    AuditEvent.action == AuditAction.MEMBER_JOINED,
                )
            )
            return (
                response.status_code,
                "whadio_session" in response.cookies and folder is not None,
                memberships or 0,
                audits or 0,
            )

    # Assert
    assert async_database.run(scenario) == (201, True, 2, 1)


@pytest.mark.parametrize("operation", ["preview", "accept", "register", "decline"])
@pytest.mark.parametrize("invalid", ["token", "expired", "cancelled", "creator", "unknown"])
def test_dead_links_have_one_refusal(
    async_database: AsyncDatabase, operation: str, invalid: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        async with AsyncDatabase.api_client(session) as client:
            owner, invitation_id, token = await issue(client, session, f"{uuid4()}@example.com")
            invitation = await session.get(Invitation, invitation_id)
            assert invitation is not None
            if invalid == "token":
                token = uuid4().hex
            elif invalid == "expired":
                invitation.created_at = datetime.now(UTC) - timedelta(days=8)
                invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
            elif invalid == "cancelled":
                invitation.status = InvitationStatus.CANCELLED
            elif invalid == "creator":
                member = await session.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == invitation.workspace_id,
                        WorkspaceMembership.user_id == owner,
                    )
                )
                assert member is not None
                member.role = WorkspaceRole.MEMBER
            else:
                invitation_id = uuid4()
            await session.flush()
            payload: dict[str, str | bool] = {"token": token}
            if operation == "register":
                payload.update(name="New member", password=PASSWORD, accept_terms=True)
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/{operation}", json=payload
            )
            return (
                response.status_code,
                '"code":"LINK_INVALID"' in response.text and token not in response.text,
            )

    # Assert
    assert async_database.run(scenario) == (404, True)


def test_accept_is_idempotent_and_does_not_repeat_the_audit(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool, int]:
        async with AsyncDatabase.api_client(session) as client:
            user = await AsyncDatabase.add_account(session, PASSWORD)
            _, invitation_id, token = await issue(client, session, user.email.upper())
            await client.post("/api/v1/sessions", json={"email": user.email, "password": PASSWORD})
            path = f"/api/v1/invitations/{invitation_id}/accept"
            # Act
            first = await client.post(path, json={"token": token})
            second = await client.post(path, json={"token": token})
            count = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == user.user_id,
                    AuditEvent.action == AuditAction.MEMBER_JOINED,
                )
            )
            return first.status_code, first.content == second.content, count or 0

    # Assert
    assert async_database.run(scenario) == (200, True, 1)


def test_preview_and_decline_are_public_and_decline_consumes_link(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int, int]:
        async with AsyncDatabase.api_client(session) as client:
            _, invitation_id, token = await issue(client, session, f"{uuid4()}@example.com")
            await client.delete("/api/v1/sessions/current")
            path = f"/api/v1/invitations/{invitation_id}"
            # Act
            preview = await client.post(f"{path}/preview", json={"token": token})
            decline = await client.post(f"{path}/decline", json={"token": token})
            again = await client.post(f"{path}/preview", json={"token": token})
            return preview.status_code, decline.status_code, again.status_code

    # Assert
    assert async_database.run(scenario) == (200, 200, 404)


@pytest.mark.parametrize(("password", "terms"), [("weak", True), (PASSWORD, False)])
def test_invalid_registration_keeps_invitation_pending(
    async_database: AsyncDatabase, password: str, *, terms: bool
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, InvitationStatus]:
        async with AsyncDatabase.api_client(session) as client:
            _, invitation_id, token = await issue(client, session, f"{uuid4()}@example.com")
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/register",
                json={
                    "token": token,
                    "name": "New member",
                    "password": password,
                    "accept_terms": terms,
                },
            )
            invitation = await session.get(Invitation, invitation_id)
            assert invitation is not None
            return response.status_code, invitation.status

    # Assert
    assert async_database.run(scenario) == (422, InvitationStatus.PENDING)


@pytest.mark.parametrize(("operation", "expected"), [("accept", 403), ("register", 409)])
def test_valid_link_reports_wrong_account_or_existing_account(
    async_database: AsyncDatabase, operation: str, expected: int
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            user = await AsyncDatabase.add_account(session, PASSWORD)
            _, invitation_id, token = await issue(client, session, user.email)
            payload: dict[str, str | bool] = {"token": token}
            if operation == "register":
                payload.update(name="New member", password=PASSWORD, accept_terms=True)
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/{operation}", json=payload
            )
            return response.status_code

    # Assert
    assert async_database.run(scenario) == expected


def test_accept_requires_a_browser_session(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            _, invitation_id, token = await issue(client, session, f"{uuid4()}@example.com")
            await client.delete("/api/v1/sessions/current")
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/accept", json={"token": token}
            )
            return response.status_code

    # Assert
    assert async_database.run(scenario) == 401


def test_replaced_link_cannot_be_redeemed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            email = f"{uuid4()}@example.com"
            _, invitation_id, token = await issue(client, session, email)
            invitation = await session.get(Invitation, invitation_id)
            assert invitation is not None
            await client.post(
                f"/api/v1/workspaces/{invitation.workspace_id}/invitations",
                json={"email": email, "role": "member"},
            )
            # Act
            response = await client.post(
                f"/api/v1/invitations/{invitation_id}/preview", json={"token": token}
            )
            return response.status_code

    # Assert
    assert async_database.run(scenario) == 404
