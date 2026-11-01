import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from conftest import AsyncDatabase

from ..shared.database import DatabaseSettings
from .enums import InvitationRole, InvitationStatus, WorkspaceRole
from .models import Invitation, PendingRegistration, WorkspaceMembership
from .repositories import InvitationRepository, MembershipRepository, RegistrationRepository


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


@pytest.mark.slow
def test_registration_cleanup_removes_only_expired_links_including_the_boundary(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        now = datetime.now(UTC)
        repository = RegistrationRepository(session)
        await repository.delete_expired(now)
        ids = [
            await repository.issue(
                f"{uuid4()}@example.com",
                uuid4().hex,
                now - timedelta(days=2),
                now + timedelta(microseconds=offset),
            )
            for offset in (-1, 0, 1)
        ]
        # Act
        removed = await repository.delete_expired(now)
        remaining = set(
            await session.scalars(
                select(PendingRegistration.pending_registration_id).where(
                    PendingRegistration.pending_registration_id.in_(ids)
                )
            )
        )
        return removed, remaining == {ids[-1]}

    # Assert
    assert async_database.run(scenario) == (2, True)


@pytest.mark.slow
def test_registration_cleanup_is_idempotent(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        now = datetime.now(UTC)
        repository = RegistrationRepository(session)
        await repository.issue(f"{uuid4()}@example.com", uuid4().hex, now - timedelta(days=2), now)
        await repository.delete_expired(now)
        # Act
        return await repository.delete_expired(now)

    # Assert
    assert async_database.run(scenario) == 0


@pytest.mark.slow
def test_invitation_cleanup_removes_all_expired_statuses_and_preserves_valid_rows(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int, int]:
        actor, _ = await AsyncDatabase.add_workspace(session)
        workspace = await session.scalar(
            select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == actor)
        )
        now = datetime.now(UTC)
        for status in InvitationStatus:
            for offset in (-1, 0, 1):
                session.add(
                    Invitation(
                        workspace_id=workspace,
                        invited_email=f"{uuid4()}@example.com",
                        role=InvitationRole.MEMBER,
                        invited_by_user_id=actor,
                        status=status,
                        token_hash=uuid4().hex,
                        created_at=now - timedelta(days=7),
                        expires_at=now + timedelta(seconds=offset),
                    )
                )
        await session.flush()
        repository = InvitationRepository(session)
        # Act
        removed = await repository.delete_expired(now)
        repeated = await repository.delete_expired(now)
        remaining = len(
            list(
                await session.scalars(
                    select(Invitation).where(Invitation.workspace_id == workspace)
                )
            )
        )
        return removed, repeated, remaining

    # Assert
    assert async_database.run(scenario) == (8, 0, 4)


@pytest.mark.slow
def test_inviter_lock_permits_foreign_key_checks_and_serializes_invites(
    database_settings: DatabaseSettings, committed_workspace: tuple[UUID, UUID]
) -> None:
    # Arrange
    actor, _ = committed_workspace

    async def scenario() -> tuple[bool, bool]:
        engine = create_async_engine(database_settings.application_url(), hide_parameters=True)
        try:
            async with AsyncSession(engine) as session, session.begin():
                # Act
                await InvitationRepository(session).lock_inviter(actor)
                return (
                    row_available(
                        database_settings,
                        'SELECT user_id FROM "user" WHERE user_id = :workspace '
                        "FOR KEY SHARE NOWAIT",
                        actor,
                    ),
                    row_available(
                        database_settings,
                        'SELECT user_id FROM "user" WHERE user_id = :workspace '
                        "FOR NO KEY UPDATE NOWAIT",
                        actor,
                    ),
                )
        finally:
            await engine.dispose()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == (True, False)
