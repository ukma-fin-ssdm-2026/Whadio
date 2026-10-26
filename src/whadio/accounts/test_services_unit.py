import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ..audit.services import McpKeyCreated, McpKeyRevoked
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .repositories import McpKeyRevokeResult, PersonalMcpKey
from .services import McpKeyService

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


class Keys:
    def __init__(self) -> None:
        self.keys: dict[UUID, tuple[UUID, PersonalMcpKey, str]] = {}

    async def of_user(self, user_id: UUID, page: ListWindow | None = None) -> list[PersonalMcpKey]:
        found = [key for owner_id, key, _ in self.keys.values() if owner_id == user_id]
        return found if page is None else found[: page.limit]

    async def add(
        self, user_id: UUID, key_hash: str, expires_at: datetime | None, now: datetime
    ) -> PersonalMcpKey:
        key = PersonalMcpKey(uuid4(), now, expires_at, None)
        self.keys[key.key_id] = (user_id, key, key_hash)
        return key

    async def revoke(self, user_id: UUID, key_id: UUID, now: datetime) -> McpKeyRevokeResult:
        stored = self.keys.get(key_id)
        if stored is None or stored[0] != user_id:
            return McpKeyRevokeResult.NOT_FOUND
        owner_id, key, key_hash = stored
        if key.revoked_at is not None:
            return McpKeyRevokeResult.ALREADY_REVOKED
        self.keys[key_id] = (
            owner_id,
            PersonalMcpKey(key.key_id, key.created_at, key.expires_at, now),
            key_hash,
        )
        return McpKeyRevokeResult.REVOKED


class Audit:
    def __init__(self) -> None:
        self.events: list[McpKeyCreated | McpKeyRevoked] = []

    async def write(self, event: McpKeyCreated | McpKeyRevoked) -> None:
        self.events.append(event)


def test_created_mcp_key_is_stored_only_as_a_hash() -> None:
    # Arrange
    user_id = uuid4()
    keys = Keys()

    async def scenario() -> bool:
        created = await McpKeyService(keys, Audit()).create(user_id, 30, NOW)
        stored_hash = keys.keys[created.key.key_id][2]
        return (
            stored_hash == hashlib.sha256(created.secret.encode()).hexdigest()
            and stored_hash != created.secret
        )

    # Act
    stored_only_as_hash = asyncio.run(scenario())
    # Assert
    assert stored_only_as_hash


def test_created_mcp_key_has_requested_expiry() -> None:
    # Arrange
    async def scenario() -> datetime | None:
        created = await McpKeyService(Keys(), Audit()).create(uuid4(), 30, NOW)
        return created.key.expires_at

    # Act
    expires_at = asyncio.run(scenario())
    # Assert
    assert expires_at == NOW + timedelta(days=30)


def test_created_mcp_key_is_audited() -> None:
    # Arrange
    user_id = uuid4()
    audit = Audit()

    async def scenario() -> tuple[list[McpKeyCreated | McpKeyRevoked], UUID]:
        created = await McpKeyService(Keys(), audit).create(user_id, None, NOW)
        return audit.events, created.key.key_id

    # Act
    events, key_id = asyncio.run(scenario())
    # Assert
    assert events == [McpKeyCreated(user_id, key_id, NOW)]


def test_repeated_mcp_key_revocation_is_audited_once() -> None:
    # Arrange
    user_id = uuid4()
    keys, audit = Keys(), Audit()

    async def scenario() -> tuple[list[McpKeyCreated | McpKeyRevoked], UUID]:
        service = McpKeyService(keys, audit)
        created = await service.create(user_id, None, NOW)
        audit.events.clear()
        await service.revoke(user_id, created.key.key_id, NOW)
        await service.revoke(user_id, created.key.key_id, NOW)
        return audit.events, created.key.key_id

    # Act
    events, key_id = asyncio.run(scenario())
    # Assert
    assert events == [McpKeyRevoked(user_id, key_id, NOW)]


def test_user_cannot_revoke_another_users_mcp_key() -> None:
    # Arrange
    owner_id = uuid4()
    keys = Keys()

    async def scenario() -> None:
        created = await McpKeyService(keys, Audit()).create(owner_id, None, NOW)
        await McpKeyService(keys, Audit()).revoke(uuid4(), created.key.key_id, NOW)

    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(scenario())
    # Assert
    assert failure.value.code is Failure.NOT_FOUND


def test_personal_mcp_key_is_inactive_after_expiry() -> None:
    # Arrange
    key = PersonalMcpKey(uuid4(), NOW - timedelta(days=2), NOW - timedelta(days=1), None)
    # Act
    active = key.is_active(NOW)
    # Assert
    assert not active
