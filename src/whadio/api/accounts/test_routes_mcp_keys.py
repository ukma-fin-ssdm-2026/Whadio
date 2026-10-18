import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from conftest import AsyncDatabase

from ...accounts.enums import SessionKind
from ...accounts.models import McpKey, Session, User
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ..core.schemas import Page
from ..mcp_server import build_mcp_server
from .schemas import McpKeyCreated, McpKeyRead

pytestmark = pytest.mark.slow


async def _session_token(session: AsyncSession, user: User, kind: SessionKind) -> str:
    token = uuid4().hex
    now = datetime.now(UTC)
    session.add(
        Session(
            user_id=user.user_id,
            kind=kind,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    await session.flush()
    return token


@asynccontextmanager
async def _signed_in_client(session: AsyncSession, user: User) -> AsyncGenerator[AsyncClient]:
    token = await _session_token(session, user, SessionKind.BROWSER)
    async with AsyncDatabase.api_client(session) as client:
        client.cookies.set("whadio_session", token)
        yield client


async def _mcp_key_works(
    session: AsyncSession, secret: str, monkeypatch: pytest.MonkeyPatch
) -> bool:
    request = Request(
        {"type": "http", "headers": [(b"authorization", f"Bearer {secret}".encode())]}
    )
    monkeypatch.setattr("whadio.api.mcp_server.get_http_request", lambda: request)

    class Transactions:
        @asynccontextmanager
        async def transaction(self) -> AsyncGenerator[AsyncSession]:
            async with session.begin_nested():
                yield session

    try:
        async with Client(build_mcp_server(Transactions)) as client:
            await client.call_tool("list_meetings")
    except ToolError:
        return False
    return True


def test_created_mcp_key_is_stored_only_as_a_hash(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            response = await client.post("/api/v1/users/me/mcp-keys", json={})
        created = McpKeyCreated.model_validate_json(response.content)
        stored = await session.get(McpKey, created.id)
        return (
            stored is not None
            and stored.key_hash == hashlib.sha256(created.secret.encode()).hexdigest()
            and stored.key_hash != created.secret
        )

    # Act
    stored_only_as_hash = async_database.run(scenario)
    # Assert
    assert stored_only_as_hash


def test_created_mcp_key_is_audited(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            response = await client.post("/api/v1/users/me/mcp-keys", json={})
        created = McpKeyCreated.model_validate_json(response.content)
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.subject_id == created.id))
        return (
            audit is not None
            and audit.action is AuditAction.MCP_KEY_CREATED
            and audit.actor_user_id == user.user_id
            and audit.subject_id == created.id
        )

    # Act
    audited = async_database.run(scenario)
    # Assert
    assert audited


def test_created_mcp_key_authenticates_an_mcp_tool(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            response = await client.post("/api/v1/users/me/mcp-keys", json={})
        secret = McpKeyCreated.model_validate_json(response.content).secret
        return await _mcp_key_works(session, secret, monkeypatch)

    # Act
    authenticated = async_database.run(scenario)
    # Assert
    assert authenticated


def test_created_mcp_key_can_never_expire(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> datetime | None:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            response = await client.post("/api/v1/users/me/mcp-keys")
        return McpKeyCreated.model_validate_json(response.content).expires_at

    # Act
    expires_at = async_database.run(scenario)
    # Assert
    assert expires_at is None


def test_list_mcp_keys_includes_inactive_keys_newest_first(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[bool]:
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
            response = await client.get("/api/v1/users/me/mcp-keys")
        page = Page[McpKeyRead].model_validate_json(response.content)
        return [item.is_active for item in page.items]

    # Act
    active_states = async_database.run(scenario)
    # Assert
    assert active_states == [True, False]


def test_list_mcp_keys_never_returns_secrets(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            await client.post("/api/v1/users/me/mcp-keys", json={})
            response = await client.get("/api/v1/users/me/mcp-keys")
        return b"secret" not in response.content and b"key_hash" not in response.content

    # Act
    secrets_hidden = async_database.run(scenario)
    # Assert
    assert secrets_hidden


def test_list_mcp_keys_uses_an_opaque_cursor(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        now = datetime.now(UTC)
        session.add_all(
            [
                McpKey(
                    user_id=user.user_id,
                    key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    created_at=now - timedelta(minutes=index),
                    expires_at=None,
                    revoked_at=None,
                )
                for index in range(3)
            ]
        )
        await session.flush()
        async with _signed_in_client(session, user) as client:
            first = Page[McpKeyRead].model_validate_json(
                (await client.get("/api/v1/users/me/mcp-keys?limit=2")).content
            )
            second = Page[McpKeyRead].model_validate_json(
                (
                    await client.get(
                        "/api/v1/users/me/mcp-keys",
                        params={"limit": 2, "cursor": first.pagination.next_cursor},
                    )
                ).content
            )
        ids = [item.id for item in first.items + second.items]
        cursor = first.pagination.next_cursor
        return (
            len(ids) == 3
            and len(set(ids)) == 3
            and isinstance(cursor, str)
            and not cursor.isdigit()
        )

    # Act
    cursor_pages_all_keys = async_database.run(scenario)
    # Assert
    assert cursor_pages_all_keys


def test_repeated_mcp_key_revocation_is_audited_once(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            created = McpKeyCreated.model_validate_json(
                (await client.post("/api/v1/users/me/mcp-keys", json={})).content
            )
            await client.delete(f"/api/v1/users/me/mcp-keys/{created.id}")
            await client.delete(f"/api/v1/users/me/mcp-keys/{created.id}")
        count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.subject_id == created.id,
                AuditEvent.action == AuditAction.MCP_KEY_REVOKED,
            )
        )
        return count or 0

    # Act
    audits = async_database.run(scenario)
    # Assert
    assert audits == 1


def test_user_cannot_revoke_another_users_mcp_key(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        owner = await AsyncDatabase.add_account(session, uuid4().hex)
        other = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, other) as client:
            created = McpKeyCreated.model_validate_json(
                (await client.post("/api/v1/users/me/mcp-keys", json={})).content
            )
        async with _signed_in_client(session, owner) as client:
            response = await client.delete(f"/api/v1/users/me/mcp-keys/{created.id}")
        return response.status_code

    # Act
    status = async_database.run(scenario)
    # Assert
    assert status == 404


def test_revoked_mcp_key_is_refused(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            created = McpKeyCreated.model_validate_json(
                (await client.post("/api/v1/users/me/mcp-keys", json={})).content
            )
            await client.delete(f"/api/v1/users/me/mcp-keys/{created.id}")
        return await _mcp_key_works(session, created.secret, monkeypatch)

    # Act
    authenticated = async_database.run(scenario)
    # Assert
    assert not authenticated


def test_expired_mcp_key_is_refused(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        secret = uuid4().hex
        now = datetime.now(UTC)
        session.add(
            McpKey(
                user_id=user.user_id,
                key_hash=hashlib.sha256(secret.encode()).hexdigest(),
                created_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
                revoked_at=None,
            )
        )
        await session.flush()
        return await _mcp_key_works(session, secret, monkeypatch)

    # Act
    authenticated = async_database.run(scenario)
    # Assert
    assert not authenticated


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, 422), (1, 201), (2, 201), (180, 201), (364, 201), (365, 201), (366, 422)],
)
def test_mcp_key_expiry_days_enforce_boundaries(
    async_database: AsyncDatabase, days: int, expected: int
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        async with _signed_in_client(session, user) as client:
            response = await client.post(
                "/api/v1/users/me/mcp-keys", json={"expires_in_days": days}
            )
        return response.status_code

    # Act
    status = async_database.run(scenario)
    # Assert
    assert status == expected


def test_mcp_keys_require_browser_authentication(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            response = await client.get("/api/v1/users/me/mcp-keys")
        return response.status_code

    # Act
    status = async_database.run(scenario)
    # Assert
    assert status == 401


def test_extension_session_cannot_manage_mcp_keys(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, uuid4().hex)
        token = await _session_token(session, user, SessionKind.EXTENSION)
        async with AsyncDatabase.api_client(session) as client:
            response = await client.get(
                "/api/v1/users/me/mcp-keys", headers={"Authorization": f"Bearer {token}"}
            )
        return response.status_code

    # Act
    status = async_database.run(scenario)
    # Assert
    assert status == 401
