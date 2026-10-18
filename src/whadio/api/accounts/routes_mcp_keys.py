from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from ...accounts.repositories import PersonalMcpKey
from ..composition import McpKeys
from ..core.errors import DOC_INVALID, DOC_MALFORMED, DOC_UNAUTHENTICATED, error_responses
from ..core.schemas import Page, PageQuery, paginate
from .auth import BrowserUser
from .schemas import McpKeyCreate, McpKeyCreated, McpKeyRead

router = APIRouter(prefix="/users/me/mcp-keys", tags=["accounts"])


def _read(key: PersonalMcpKey, now: datetime) -> McpKeyRead:
    return McpKeyRead(
        id=key.key_id,
        created_at=key.created_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        is_active=key.revoked_at is None and (key.expires_at is None or key.expires_at > now),
    )


@router.get(
    "",
    summary="List my MCP keys",
    description="Lists the caller's keys newest first, including revoked and expired keys. "
    "Secrets are never returned.",
    response_description="A page of personal MCP keys",
    responses=error_responses({401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def list_mcp_keys(
    query: Annotated[PageQuery, Query()], user: BrowserUser, keys: McpKeys
) -> Page[McpKeyRead]:
    now = datetime.now(UTC)
    return paginate([_read(key, now) for key in await keys.list(user.id)], query)


@router.post(
    "",
    status_code=201,
    summary="Create an MCP key",
    description="Creates a personal key for AI assistants. The secret is shown once and only "
    "its SHA-256 hash is stored.",
    response_description="The new key and its one-time secret",
    responses=error_responses({400: DOC_MALFORMED, 401: DOC_UNAUTHENTICATED, 422: DOC_INVALID}),
)
async def create_mcp_key(payload: McpKeyCreate, user: BrowserUser, keys: McpKeys) -> McpKeyCreated:
    now = datetime.now(UTC)
    created = await keys.create(user.id, payload.expires_in_days, now)
    key = _read(created.key, now)
    return McpKeyCreated(
        id=key.id,
        created_at=key.created_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        is_active=key.is_active,
        secret=created.secret,
    )


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Revoke an MCP key",
    description="Revokes one of the caller's keys. Revoking an already revoked key is harmless.",
    response_description="Key revoked",
    responses=error_responses(
        {401: DOC_UNAUTHENTICATED, 404: "`NOT_FOUND`: no such key among the caller's own"}
    ),
)
async def revoke_mcp_key(
    key_id: Annotated[UUID, Path(description="MCP key identifier")],
    user: BrowserUser,
    keys: McpKeys,
) -> None:
    await keys.revoke(user.id, key_id, datetime.now(UTC))
