import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..shared.database import DatabaseSettings
from .enums import WorkspaceRole
from .repositories import MembershipRepository


@dataclass(frozen=True)
class MembershipLocks:
    role: WorkspaceRole | None
    workspace_available: bool
    membership_available: bool


def row_available(settings: DatabaseSettings, statement: str, workspace: UUID) -> bool:
    engine = create_engine(settings.application_url(), hide_parameters=True)
    try:
        with engine.connect() as connection, connection.begin():
            try:
                connection.execute(text(statement), {"workspace": workspace})
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != "55P03":
                    raise
                return False
            return True
    finally:
        engine.dispose()


async def membership_locks(
    settings: DatabaseSettings, actor: UUID, workspace: UUID, *, locked: bool
) -> MembershipLocks:
    engine = create_async_engine(settings.application_url(), hide_parameters=True)
    try:
        async with AsyncSession(engine) as session, session.begin():
            repository = MembershipRepository(session)
            role = (
                await repository.lock_role(workspace, actor)
                if locked
                else await repository.role(workspace, actor)
            )
            return MembershipLocks(
                role=role,
                workspace_available=row_available(
                    settings,
                    "SELECT workspace_id FROM workspace WHERE workspace_id = :workspace "
                    "FOR KEY SHARE NOWAIT",
                    workspace,
                ),
                membership_available=row_available(
                    settings,
                    "SELECT user_id FROM workspace_membership WHERE workspace_id = :workspace "
                    "FOR UPDATE NOWAIT",
                    workspace,
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.slow
def test_permission_lookup_does_not_lock_workspace_or_membership(
    database_settings: DatabaseSettings, committed_workspace: tuple[UUID, UUID]
) -> None:
    # Arrange
    actor, workspace = committed_workspace
    # Act
    observed = asyncio.run(
        membership_locks(database_settings, actor, workspace, locked=False),
        loop_factory=asyncio.SelectorEventLoop,
    )
    # Assert
    assert observed == MembershipLocks(
        role=WorkspaceRole.OWNER, workspace_available=True, membership_available=True
    )


@pytest.mark.slow
def test_folder_permission_lock_blocks_workspace_key_share_and_membership_changes(
    database_settings: DatabaseSettings, committed_workspace: tuple[UUID, UUID]
) -> None:
    # Arrange
    actor, workspace = committed_workspace
    # Act
    observed = asyncio.run(
        membership_locks(database_settings, actor, workspace, locked=True),
        loop_factory=asyncio.SelectorEventLoop,
    )
    # Assert
    assert observed == MembershipLocks(
        role=WorkspaceRole.OWNER, workspace_available=False, membership_available=False
    )
