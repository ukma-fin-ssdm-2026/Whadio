import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastmcp.utilities.lifespan import combine_lifespans
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from . import meta
from .accounts import routes_sessions, routes_workspaces
from .accounts.fixtures import DEMO_EMAIL, DEMO_PASSWORD, TEAM_WORKSPACE_ID, seed_demo_user
from .core.db import DEFAULT_DATABASE_URL, create_tables
from .core.errors import register_error_handlers
from .mcp_server import build_mcp_server
from .meetings import routes as meeting_routes
from .meetings.fixtures import DESIGN_SYNC_MEETING_ID, SPRINT_12_MEETING_ID, seed_demo_meetings
from .openapi_export import export_openapi

API_VERSION = "0.1.0"

DESCRIPTION = f"""
Whadio records Google Meet calls from the browser, transcribes them with speaker labels and
writes notes, inside workspaces with roles, restrictions and sharing.

This server is mostly a **stub**: signing in and out use real accounts and sessions stored in
the database, while every other endpoint answers with fixed demo data, and its writes return the
result they would have but store nothing. Only part of the designed API is implemented; the
full design is in `docs/api/api-design.md`.

## Quick start
1. `POST /api/v1/sessions` with `{DEMO_EMAIL}` and the password `{DEMO_PASSWORD}`. The browser
   keeps the session cookie, so every later call in this page is signed in.
2. `GET /api/v1/workspaces`, then `GET /api/v1/workspaces/{TEAM_WORKSPACE_ID}/meetings`.
3. `GET /api/v1/meetings/{SPRINT_12_MEETING_ID}/transcript` is processed;
   `{DESIGN_SYNC_MEETING_ID}` is still queued and answers `409`.

## Conventions
- **Errors:** every 4xx and 5xx body is `{{"error": {{"code", "message", "details",
  "request_id"}}}}`. Branch on `code`; `request_id` equals the `X-Request-ID` response header.
- **Lists:** `limit` (1-100, default 20) and `cursor`; responses are
  `{{"items": [...], "pagination": {{"limit", "next_cursor", "has_more"}}}}`.
- **Visibility:** a resource the caller cannot see is `404`, never `403`, so its existence does
  not leak. `403` means the caller can see it but their role does not allow the action.
- **Time:** ISO 8601 with an offset; returned in UTC.
"""

TAGS = [
    {"name": "accounts", "description": "Sessions: signing in and out"},
    {"name": "workspaces", "description": "Workspaces the caller belongs to"},
    {"name": "meetings", "description": "Meetings, recording upload and transcripts"},
    {"name": "notes", "description": "Generated notes and their regeneration"},
    {"name": "meta", "description": "Operational endpoints"},
]

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def _export_spec(app: FastAPI) -> AsyncGenerator[None]:
    for path in export_openapi(app):
        logger.info("Wrote %s", path)
    yield


@asynccontextmanager
async def _database(app: FastAPI) -> AsyncGenerator[None]:
    engine = create_async_engine(app.state.database_url)
    await create_tables(engine)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with app.state.sessionmaker() as db:
        await seed_demo_user(db)
        await seed_demo_meetings(db)
    yield
    await engine.dispose()


def create_app(database: str | None = None, recordings: Path | None = None) -> FastAPI:
    mcp_app = build_mcp_server().http_app(path="/")
    app = FastAPI(
        title="Whadio API",
        description=DESCRIPTION.strip(),
        version=API_VERSION,
        openapi_tags=TAGS,
        docs_url="/api-docs",
        lifespan=combine_lifespans(_export_spec, _database, mcp_app.lifespan),
    )
    app.state.database_url = database or os.environ.get(
        "WHADIO_DATABASE_URL", DEFAULT_DATABASE_URL
    )
    # A local folder until the team runs object storage (S3).
    app.state.recordings_dir = recordings or Path(
        os.environ.get("WHADIO_RECORDINGS_DIR", "recordings")
    )
    v1 = APIRouter(prefix="/api/v1")
    for module in (routes_sessions, routes_workspaces, meeting_routes):
        v1.include_router(module.router)
    app.include_router(v1)
    app.include_router(meta.router)
    app.mount("/mcp", mcp_app)
    register_error_handlers(app)
    return app
