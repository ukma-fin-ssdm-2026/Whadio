from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from .accounts.enums import SessionKind, WorkspaceRole
from .accounts.models import Session, User, Workspace, WorkspaceMembership
from .accounts.passwords import Argon2PasswordHasher
from .dev_user import ensure_dev_user
from .meetings.models import Folder

pytestmark = pytest.mark.slow
FIRST_PASSWORD = uuid4().hex
SECOND_PASSWORD = uuid4().hex


def test_new_dev_user_gets_a_personal_workspace_and_default_folder(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    email = f"{uuid4()}@example.com"

    async def scenario(session: AsyncSession) -> tuple[bool, str, WorkspaceRole, str]:
        # Act
        created = await ensure_dev_user(
            session,
            email=email,
            name="Margaret Hamilton",
            password=FIRST_PASSWORD,
        )
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        membership = await session.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.user_id)
        )
        assert membership is not None
        workspace = await session.get(Workspace, membership.workspace_id)
        folder = await session.scalar(
            select(Folder).where(Folder.workspace_id == membership.workspace_id)
        )
        assert workspace is not None
        assert folder is not None
        return created, workspace.name, membership.role, folder.name

    created, workspace_name, role, folder_name = async_database.run(scenario)

    # Assert
    assert created
    assert workspace_name == "Margaret Hamilton"
    assert role is WorkspaceRole.OWNER
    assert folder_name == "default"


def test_existing_dev_user_password_is_updated_without_another_workspace(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    email = f"{uuid4()}@example.com"

    async def scenario(session: AsyncSession) -> tuple[bool, bool, int, int]:
        await ensure_dev_user(
            session,
            email=email,
            name="Margaret Hamilton",
            password=FIRST_PASSWORD,
        )
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        now = datetime.now(UTC)
        session.add_all(
            [
                Session(
                    user_id=user.user_id,
                    kind=kind,
                    token_hash=uuid4().hex,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                )
                for kind in (SessionKind.BROWSER, SessionKind.EXTENSION)
            ]
        )
        await session.flush()

        created = await ensure_dev_user(
            session,
            email=email,
            name="Margaret Hamilton",
            password=SECOND_PASSWORD,
        )
        workspace_count = await session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user.user_id)
        )
        session_count = await session.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == user.user_id)
        )
        return (
            created,
            Argon2PasswordHasher().verify(user.password_hash, SECOND_PASSWORD),
            workspace_count or 0,
            session_count or 0,
        )

    created, password_matches, workspace_count, session_count = async_database.run(scenario)

    # Assert
    assert not created
    assert password_matches
    assert workspace_count == 1
    assert session_count == 0


def test_existing_dev_user_email_match_ignores_case(async_database: AsyncDatabase) -> None:
    # Arrange
    email = f"Margaret.{uuid4().hex}@Example.com"

    async def scenario(session: AsyncSession) -> tuple[bool, int]:
        await ensure_dev_user(
            session,
            email=email,
            name="Margaret Hamilton",
            password=FIRST_PASSWORD,
        )

        # Act
        created = await ensure_dev_user(
            session,
            email=email.swapcase(),
            name="Margaret Hamilton",
            password=SECOND_PASSWORD,
        )
        user_count = await session.scalar(
            select(func.count()).select_from(User).where(func.lower(User.email) == email.lower())
        )
        return created, user_count or 0

    created, user_count = async_database.run(scenario)

    # Assert
    assert not created
    assert user_count == 1
