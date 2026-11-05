import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import override
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...access_policy.models import MeetingAccessGrant
from ...accounts.enums import InvitationRole, WorkspaceRole
from ...accounts.member_repository import MemberRepository
from ...accounts.members import MemberService
from ...accounts.models import User, Workspace, WorkspaceMembership
from ...accounts.repositories import MembershipRepository
from ...accounts.services import WorkspaceMembershipService
from ...audit.models import AuditEvent
from ...audit.services import AuditWriter
from ...meetings.enums import AccessMode
from ...meetings.models import Folder, Meeting
from ...shared.database import (
    Database,
    DatabaseSettings,
    MigrationSettings,
    create_migration_engine,
)
from ...shared.errors import UseCaseError
from ..composition import meeting_service

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


@dataclass(frozen=True)
class World:
    database: Database
    workspace: UUID
    owner: UUID
    moderator: UUID
    member: UUID
    meeting: UUID
    archive: UUID


@asynccontextmanager
async def world(settings: DatabaseSettings) -> AsyncGenerator[World]:
    database = Database(settings)
    users: list[UUID] = []
    workspace: UUID | None = None
    try:
        async with database.transaction() as session:
            owner, folder = await AsyncDatabase.add_workspace(session)
            users.append(owner)
            workspace = await session.scalar(
                select(Folder.workspace_id).where(Folder.folder_id == folder)
            )
            assert workspace is not None
            moderator = (await AsyncDatabase.add_account(session, PASSWORD)).user_id
            member = (await AsyncDatabase.add_account(session, PASSWORD)).user_id
            users.extend([moderator, member])
            session.add_all(
                [
                    WorkspaceMembership(
                        workspace_id=workspace, user_id=moderator, role=WorkspaceRole.MODERATOR
                    ),
                    WorkspaceMembership(
                        workspace_id=workspace, user_id=member, role=WorkspaceRole.MEMBER
                    ),
                ]
            )
            meeting = await AsyncDatabase.add_meeting(
                session, (owner, folder), access_mode=AccessMode.RESTRICTED
            )
            session.add(
                MeetingAccessGrant(meeting_id=meeting, user_id=moderator, granted_by_user_id=owner)
            )
            archive = Folder(workspace_id=workspace, name="Archive")
            session.add(archive)
            await session.flush()
        yield World(database, workspace, owner, moderator, member, meeting, archive.folder_id)
    finally:
        await database.close()

        def cleanup() -> None:
            engine = create_migration_engine(
                MigrationSettings.model_validate(
                    {"host": settings.host, "port": settings.port, "name": settings.name}
                )
            )
            try:
                with engine.begin() as connection:
                    # Only the owner role may remove the audit rows of committed test fixtures.
                    connection.execute(
                        delete(AuditEvent).where(AuditEvent.workspace_id == workspace)
                    )
                    connection.execute(
                        delete(Meeting).where(
                            Meeting.folder_id.in_(
                                select(Folder.folder_id).where(Folder.workspace_id == workspace)
                            )
                        )
                    )
                    connection.execute(delete(Workspace).where(Workspace.workspace_id == workspace))
                    connection.execute(delete(User).where(User.user_id.in_(users)))
            finally:
                engine.dispose()

        await asyncio.to_thread(cleanup)


class ObservedMembershipRepository(MembershipRepository):
    """Signals when its transaction is about to take the workspace's membership locks."""

    def __init__(self, session: AsyncSession, attempted: asyncio.Event) -> None:
        super().__init__(session)
        self._attempted: asyncio.Event = attempted

    @override
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        self._attempted.set()
        return await super().role(workspace_id, user_id)

    @override
    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        self._attempted.set()
        return await super().lock_role(workspace_id, user_id)


async def _operate(
    place: World, session: AsyncSession, operation: str, memberships: MembershipRepository
) -> None:
    members = MemberService(
        MemberRepository(session), WorkspaceMembershipService(memberships), AuditWriter(session)
    )
    actor, target, role = {
        "demote": (place.moderator, place.moderator, InvitationRole.MEMBER),
        "dismiss": (place.owner, place.moderator, InvitationRole.MEMBER),
        "promote": (place.moderator, place.member, InvitationRole.MODERATOR),
    }[operation]
    await members.change_role(actor, place.workspace, target, role, datetime.now(UTC))


@pytest.mark.parametrize(
    ("first", "expected"),
    [
        pytest.param(
            "dismiss", ["dismiss: done", "promote: INSUFFICIENT_ROLE"], id="demotion-first"
        ),
        pytest.param("promote", ["dismiss: done", "promote: done"], id="role-change-first"),
    ],
)
def test_a_moderators_demotion_and_their_concurrent_role_change_serialize(
    database_settings: DatabaseSettings, first: str, expected: list[str]
) -> None:
    # Arrange
    async def scenario() -> list[str]:
        async with world(database_settings) as place:
            held, attempted = asyncio.Event(), asyncio.Event()

            async def perform(operation: str) -> str:
                leads = operation == first
                if not leads:
                    await held.wait()
                try:
                    async with place.database.transaction() as session:
                        await _operate(
                            place,
                            session,
                            operation,
                            MembershipRepository(session)
                            if leads
                            else ObservedMembershipRepository(session, attempted),
                        )
                        if leads:
                            held.set()
                            await attempted.wait()
                            await asyncio.sleep(0.5)
                except UseCaseError as error:
                    return f"{operation}: {error.code.value}"
                return f"{operation}: done"

            # Act
            return sorted(
                await asyncio.wait_for(
                    asyncio.gather(perform("dismiss"), perform("promote")), timeout=20
                )
            )

    results = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)

    # Assert
    assert results == expected


def test_a_recipient_demoting_themselves_waits_for_a_concurrent_move(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> list[str]:
        async with world(database_settings) as place:
            held, attempted = asyncio.Event(), asyncio.Event()

            async def move() -> str:
                try:
                    async with place.database.transaction() as session:
                        await meeting_service(session, AuditWriter(session)).update(
                            place.moderator,
                            place.meeting,
                            datetime.now(UTC),
                            folder_id=place.archive,
                        )
                        held.set()
                        await attempted.wait()
                        await asyncio.sleep(0.5)
                except DBAPIError as error:
                    return f"move: {type(error.orig).__name__}"
                return "move: done"

            async def change() -> str:
                await held.wait()
                try:
                    async with place.database.transaction() as session:
                        await _operate(
                            place,
                            session,
                            "demote",
                            ObservedMembershipRepository(session, attempted),
                        )
                except DBAPIError as error:
                    return f"demote: {type(error.orig).__name__}"
                return "demote: done"

            # Act
            return sorted(await asyncio.wait_for(asyncio.gather(move(), change()), timeout=20))

    results = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)

    # Assert
    assert results == ["demote: done", "move: done"]
