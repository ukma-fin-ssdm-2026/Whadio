from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from .accounts.fixtures import TEAM_WORKSPACE_ID
from .accounts.models import WorkspaceMembership
from .accounts.schemas import Role
from .accounts.users import create_user
from .app import create_app

BOB_EMAIL = "bob@whadio.dev"
BOB_PASSWORD = "bob-password"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", tmp_path / "recordings")
    # https, because the session cookie is Secure and is not sent over plain http.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def bob(client: TestClient) -> UUID:
    """A second account with its own personal workspace, a plain Member of Alice's team one."""

    async def add_bob() -> UUID:
        async with client.app.state.sessionmaker() as db:
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

    return client.portal.call(add_bob)
