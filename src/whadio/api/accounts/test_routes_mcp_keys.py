import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import SessionKind
from ...accounts.models import McpKey, Session, User
from ...accounts.repositories import IdentityRepository
from ...accounts.services import IdentityService
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import McpKeyCreated, McpKeyRead

pytestmark = pytest.mark.slow


@asynccontextmanager
async def _signed_in_client(session: AsyncSession, user: User) -> AsyncGenerator[AsyncClient]:
    token = uuid4().hex
    now = datetime.now(UTC)
    session.add(
        Session(
            user_id=user.user_id,
            kind=SessionKind.BROWSER,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    await session.flush()
    async with AsyncDatabase.api_client(session) as client:
        client.cookies.set("whadio_session", token)
        yield client


def test_created_mcp_key_is_shown_once_stored_hashed_and_audited(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool, bool, bool]:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            # Act
            response = await client.post("/api/v1/users/me/mcp-keys", json={"expires_in_days": 30})
            created = McpKeyCreated.model_validate_json(response.content)
            stored = await session.get(McpKey, created.id)
            authenticated = await IdentityService(IdentityRepository(session)).mcp_user(
                created.secret, datetime.now(UTC)
            )
            audit = await session.scalar(
                select(AuditEvent).where(AuditEvent.subject_id == created.id)
            )
            return (
                response.status_code,
                stored is not None
                and stored.key_hash == hashlib.sha256(created.secret.encode()).hexdigest()
                and stored.key_hash != created.secret,
                authenticated is not None and authenticated.user_id == user.user_id,
                audit is not None
                and audit.actor_user_id == user.user_id
                and audit.action is AuditAction.MCP_KEY_CREATED,
            )

    found = async_database.run(scenario)

    # Assert
    assert found == (201, True, True, True)


def test_list_mcp_keys_includes_inactive_keys_without_secrets(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, list[bool], bool]:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        now = datetime.now(UTC)
        session.add_all(
            [
                McpKey(
                    user_id=user.user_id,
                    key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    created_at=now - timedelta(days=2),
                    expires_at=now - timedelta(days=1),
                    revoked_at=None,
                ),
                McpKey(
                    user_id=user.user_id,
                    key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    created_at=now,
                    expires_at=None,
                    revoked_at=None,
                ),
            ]
        )
        await session.flush()
        async with _signed_in_client(session, user) as client:
            # Act
            response = await client.get("/api/v1/users/me/mcp-keys")
            page = Page[McpKeyRead].model_validate_json(response.content)
            return (
                response.status_code,
                [key.is_active for key in page.items],
                b"secret" not in response.content and b"key_hash" not in response.content,
            )

    found = async_database.run(scenario)

    # Assert
    assert found == (200, [True, False], True)


def test_revoke_is_idempotent_and_cannot_revoke_another_users_key(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int, int, int, str]:
        owner = await AsyncDatabase.add_account(session, uuid4().hex)
        other = await AsyncDatabase.add_account(session, uuid4().hex)
        now = datetime.now(UTC)
        own_key = McpKey(
            user_id=owner.user_id,
            key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
            created_at=now,
            expires_at=None,
            revoked_at=None,
        )
        other_key = McpKey(
            user_id=other.user_id,
            key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
            created_at=now,
            expires_at=None,
            revoked_at=None,
        )
        session.add_all([own_key, other_key])
        await session.flush()
        async with _signed_in_client(session, owner) as client:
            # Act
            first = await client.delete(f"/api/v1/users/me/mcp-keys/{own_key.mcp_key_id}")
            repeated = await client.delete(f"/api/v1/users/me/mcp-keys/{own_key.mcp_key_id}")
            foreign = await client.delete(f"/api/v1/users/me/mcp-keys/{other_key.mcp_key_id}")
            audits = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == own_key.mcp_key_id,
                    AuditEvent.action == AuditAction.MCP_KEY_REVOKED,
                )
            )
            return (
                first.status_code,
                repeated.status_code,
                foreign.status_code,
                audits or 0,
                _error_code(foreign),
            )

    found = async_database.run(scenario)

    # Assert
    assert found == (204, 204, 404, 1, "NOT_FOUND")


def test_mcp_key_expiry_days_enforce_both_boundaries(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[int]:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            # Act
            return [
                (
                    await client.post("/api/v1/users/me/mcp-keys", json={"expires_in_days": days})
                ).status_code
                for days in (0, 1, 365, 366)
            ]

    statuses = async_database.run(scenario)

    # Assert
    assert statuses == [422, 201, 201, 422]


def test_mcp_keys_require_browser_authentication(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.get("/api/v1/users/me/mcp-keys")
            return response.status_code

    status = async_database.run(scenario)

    # Assert
    assert status == 401


def _error_code(response: Response) -> str:
    error = ErrorResponse.model_validate_json(response.content)
    return error.error.code.value
