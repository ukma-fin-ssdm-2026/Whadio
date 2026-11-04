import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import override
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...access_policy.models import MeetingAccessGrant
from ...access_policy.repositories import AccessRepository
from ...access_policy.services import AccessCollaborators, AccessService, MemberAccessRelease
from ...accounts.enums import WorkspaceRole
from ...accounts.member_repository import MemberRepository
from ...accounts.members import MemberService
from ...accounts.models import User, Workspace, WorkspaceMembership
from ...accounts.repositories import MembershipRepository
from ...accounts.services import WorkspaceMembershipService
from ...audit.models import AuditEvent
from ...audit.services import AuditWriter
from ...meetings.enums import AccessMode
from ...meetings.models import Folder, Meeting
from ...meetings.repositories import MeetingRepository
from ...shared.database import (
    Database,
    DatabaseSettings,
    MigrationSettings,
    create_migration_engine,
)
from ...shared.errors import UseCaseError
from ..composition import share_notifications

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


@dataclass(frozen=True)
class World:
    database: Database
    workspace: UUID
    owner: UUID
    moderator: UUID
    departing: UUID
    meeting: UUID


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
            departing = (await AsyncDatabase.add_account(session, PASSWORD)).user_id
            users.extend([moderator, departing])
            session.add_all(
                [
                    WorkspaceMembership(
                        workspace_id=workspace, user_id=moderator, role=WorkspaceRole.MODERATOR
                    ),
                    WorkspaceMembership(
                        workspace_id=workspace, user_id=departing, role=WorkspaceRole.MEMBER
                    ),
                ]
            )
            meeting = await AsyncDatabase.add_meeting(
                session, (owner, folder), access_mode=AccessMode.RESTRICTED
            )
            session.add(
                MeetingAccessGrant(meeting_id=meeting, user_id=moderator, granted_by_user_id=owner)
            )
        yield World(database, workspace, owner, moderator, departing, meeting)
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
    directory = WorkspaceMembershipService(memberships)
    now = datetime.now(UTC)
    if operation == "remove":
        members = MemberService(
            MemberRepository(session),
            directory,
            MemberAccessRelease(AccessRepository(session), MeetingRepository(session)),
            AuditWriter(session),
        )
        await members.remove(place.owner, place.workspace, place.departing, now)
        return
    access = AccessService(
        AccessCollaborators(
            AccessRepository(session),
            MeetingRepository(session),
            directory,
            AuditWriter(session),
            share_notifications(session),
        )
    )
    await access.replace_access(
        place.moderator, place.meeting, {place.moderator, place.departing}, now, restricted=True
    )


@pytest.mark.parametrize(
    ("first", "expected"),
    [
        pytest.param("remove", ["grant: VALIDATION_ERROR", "remove: done"], id="removal-first"),
        pytest.param("grant", ["grant: done", "remove: done"], id="access-change-first"),
    ],
)
def test_removal_and_a_concurrent_grant_to_the_departing_member_serialize(
    database_settings: DatabaseSettings, first: str, expected: list[str]
) -> None:
    # Arrange
    async def scenario() -> tuple[list[str], set[UUID], bool, set[UUID]]:
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
                except IntegrityError:
                    return f"{operation}: integrity error"
                return f"{operation}: done"

            # Act
            results = await asyncio.wait_for(
                asyncio.gather(perform("remove"), perform("grant")), timeout=20
            )
            async with place.database.transaction() as session:
                granted = set(
                    await session.scalars(
                        select(MeetingAccessGrant.user_id).where(
                            MeetingAccessGrant.meeting_id == place.meeting
                        )
                    )
                )
                still_member = (
                    await session.scalar(
                        select(WorkspaceMembership.user_id).where(
                            WorkspaceMembership.workspace_id == place.workspace,
                            WorkspaceMembership.user_id == place.departing,
                        )
                    )
                    is not None
                )
                return sorted(results), granted, still_member, {place.moderator}

    results, granted, still_member, recipients = asyncio.run(
        scenario(), loop_factory=asyncio.SelectorEventLoop
    )

    # Assert
    assert (results, granted, still_member) == (expected, recipients, False)
