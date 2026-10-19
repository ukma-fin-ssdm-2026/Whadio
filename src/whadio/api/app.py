import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastmcp.utilities.lifespan import combine_lifespans

from ..shared.database import Database
from . import meta
from .access_policy import routes as access_routes
from .accounts import routes_mcp_keys, routes_sessions, routes_workspaces
from .capture import routes as capture_routes
from .composition import (
    CompositionRoot,
    RuntimeIntegrations,
    connect_integrations,
    runtime_database,
    transaction,
)
from .core.errors import register_error_handlers
from .export import routes as export_routes
from .mcp_server import build_mcp_server
from .meetings import routes as meeting_routes
from .meetings import routes_content
from .openapi_export import export_openapi

API_VERSION = "0.1.0"

DESCRIPTION = """
Whadio records Google Meet calls from the browser, transcribes them with speaker labels and
writes notes, inside workspaces with roles, restrictions and sharing.

Sign-in, workspaces, meeting content, folders, glossary, revisions, restrictions and shares are
stored in PostgreSQL. Requests need a stored, unexpired session; MCP needs a stored personal key.
An upload is stored in object storage and queued for transcription and notes, which the workers
run.

Notes regeneration is not built yet: it returns `503 INTEGRATION_UNAVAILABLE`, as does an upload
on a server without a broker or object storage. A share access request reserves an email to the
share's creator with the request; the scheduler sends it when an SMTP relay is configured. The API
contract is in `docs/api/api-design.md`.

## Conventions
- **Errors:** every 4xx and 5xx body is `{"error": {"code", "message", "details",
  "request_id"}}`. Branch on `code`; `request_id` equals the `X-Request-ID` response header.
- **Lists:** `limit` (1-100, default 20) and `cursor`; responses are
  `{"items": [...], "pagination": {"limit", "next_cursor", "has_more"}}`.
- **Visibility:** a resource the caller cannot see is `404`, never `403`, so its existence does
  not leak. `403` means the caller can see it but their role does not allow the action.
- **Time:** ISO 8601 with an offset; returned in UTC.
"""

TAGS = [
    {"name": "accounts", "description": "Sessions: signing in and out"},
    {"name": "workspaces", "description": "Workspaces the caller belongs to"},
    {"name": "meetings", "description": "Meetings, recording upload and transcripts"},
    {"name": "notes", "description": "Generated notes and their regeneration"},
    {"name": "access", "description": "Restrictions and external shares"},
    {"name": "export", "description": "Authorized transcript and notes downloads"},
    {"name": "capture", "description": "Recording from the Chrome extension in chunks"},
    {"name": "meta", "description": "Operational endpoints"},
]

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def _export_spec(app: FastAPI) -> AsyncGenerator[None]:
    for path in export_openapi(app):
        logger.info("Wrote %s", path)
    yield


def create_app(
    database: Database | None = None, *, integrations: RuntimeIntegrations | None = None
) -> FastAPI:
    composition = CompositionRoot(database)
    mcp_app = build_mcp_server(composition.database).http_app(path="/")
    app = FastAPI(
        title="Whadio API",
        description=DESCRIPTION.strip(),
        version=API_VERSION,
        openapi_tags=TAGS,
        docs_url="/api-docs",
        lifespan=combine_lifespans(_export_spec, mcp_app.lifespan, composition.lifespan),
    )
    v1 = APIRouter(prefix="/api/v1")
    for router in (
        routes_sessions.router,
        routes_mcp_keys.router,
        routes_workspaces.router,
        meeting_routes.router,
        routes_content.router,
        access_routes.router,
        export_routes.router,
        capture_routes.router,
    ):
        v1.include_router(router)
    app.include_router(v1)
    app.include_router(meta.router)
    app.mount("/mcp", mcp_app)
    register_error_handlers(app)
    app.dependency_overrides[transaction] = composition.transaction
    app.dependency_overrides[runtime_database] = composition.database
    connect_integrations(
        app,
        RuntimeIntegrations(processing=composition.processing)
        if integrations is None
        else integrations,
    )
    return app
