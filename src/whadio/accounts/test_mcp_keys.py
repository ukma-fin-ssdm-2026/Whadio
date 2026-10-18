import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ..audit.enums import AuditAction
from ..audit.services import McpKeyChanged
from ..shared.errors import Failure, UseCaseError
from .repositories import PersonalMcpKey
from .services import McpKeyService

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


class Keys:
    def __init__(self) -> None:
        self.keys: dict[UUID, tuple[PersonalMcpKey, str]] = {}

    async def of_user(self, user_id: UUID) -> list[PersonalMcpKey]:
        del user_id
        return [stored[0] for stored in self.keys.values()]

    async def add(
        self, user_id: UUID, key_hash: str, expires_at: datetime | None, now: datetime
    ) -> PersonalMcpKey:
        del user_id
        key = PersonalMcpKey(uuid4(), now, expires_at, None)
        self.keys[key.key_id] = (key, key_hash)
        return key

    async def revoke(self, user_id: UUID, key_id: UUID, now: datetime) -> bool | None:
        del user_id
        stored = self.keys.get(key_id)
        if stored is None:
            return None
        key, key_hash = stored
        if key.revoked_at is not None:
            return False
        self.keys[key_id] = (
            PersonalMcpKey(key.key_id, key.created_at, key.expires_at, now),
            key_hash,
        )
        return True


class Audit:
    def __init__(self) -> None:
        self.events: list[McpKeyChanged] = []

    async def write(self, event: McpKeyChanged) -> None:
        self.events.append(event)


def test_created_key_has_one_time_secret_hash_expiry_and_audit() -> None:
    # Arrange
    user_id = uuid4()
    keys, audit = Keys(), Audit()

    async def scenario() -> tuple[bool, datetime | None, list[McpKeyChanged]]:
        # Act
        created = await McpKeyService(keys, audit).create(user_id, 30, NOW)
        stored_hash = keys.keys[created.key.key_id][1]
        return (
            stored_hash == hashlib.sha256(created.secret.encode()).hexdigest()
            and stored_hash != created.secret,
            created.key.expires_at,
            audit.events,
        )

    hashed, expires_at, events = asyncio.run(scenario())

    # Assert
    assert hashed
    assert expires_at == NOW + timedelta(days=30)
    assert events == [McpKeyChanged(user_id, events[0].key_id, AuditAction.MCP_KEY_CREATED, NOW)]


def test_revoke_is_idempotent_and_audited_once() -> None:
    # Arrange
    user_id = uuid4()
    keys, audit = Keys(), Audit()

    async def scenario() -> list[McpKeyChanged]:
        created = await McpKeyService(keys, audit).create(user_id, None, NOW)
        audit.events.clear()
        # Act
        await McpKeyService(keys, audit).revoke(user_id, created.key.key_id, NOW)
        await McpKeyService(keys, audit).revoke(user_id, created.key.key_id, NOW)
        return audit.events

    events = asyncio.run(scenario())

    # Assert
    assert events == [McpKeyChanged(user_id, events[0].key_id, AuditAction.MCP_KEY_REVOKED, NOW)]


def test_unknown_key_cannot_be_revoked() -> None:
    # Arrange
    service = McpKeyService(Keys(), Audit())

    async def scenario() -> None:
        # Act
        await service.revoke(uuid4(), uuid4(), NOW)

    # Assert
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(scenario())
    assert failure.value.code is Failure.NOT_FOUND
