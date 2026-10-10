from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .accounts.fixtures import TEAM_WORKSPACE_ID
from .accounts.models import WorkspaceMembership
from .accounts.schemas import Role
from .accounts.users import create_user
from .app import create_app
from .core.db import SessionFactory

BOB_EMAIL = "bob@whadio.dev"
BOB_PASSWORD: Final = "bob-password"


@pytest.fixture
def client(tmp_path: Path, sessionmaker: SessionFactory) -> Iterator[TestClient]:
    app = create_app(sessionmaker, tmp_path / "recordings")
    # https, because the session cookie is Secure and is not sent over plain http.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def sessionmaker(tmp_path: Path) -> SessionFactory:
    """The app's database sessions, for tests that set up or check rows directly."""
    return SessionFactory(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"))


@pytest.fixture
def portal(client: TestClient) -> BlockingPortal:
    """The client's event loop, where the app's database sessions have to run."""
    if client.portal is None:  # set while the client's `with` block is open
        raise RuntimeError("the test client is not running")
    return client.portal


@pytest.fixture
def bob(sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal) -> UUID:
    """A second account with its own personal workspace, a plain Member of Alice's team one."""

    async def add_bob() -> UUID:
        async with sessionmaker() as db:
            user = await create_user(db, BOB_EMAIL, "Bob Member", BOB_PASSWORD)
            db.add(
                WorkspaceMembership(
                    workspace_id=TEAM_WORKSPACE_ID,
                    user_id=user.user_id,
                    role=Role.MEMBER,
                    joined_at=datetime.now(UTC),
                )
            )
            await db.commit()
            return user.user_id

    return portal.call(add_bob)
