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
from ...access_policy.repositories import AccessRepository
from ...access_policy.services import AccessCollaborators, AccessService, MemberAccessRelease
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
from ...meetings.repositories import MeetingRepository
from ...shared.database import (
    Database,
    DatabaseSettings,
    MigrationSettings,
    create_migration_engine,
)
from ...shared.errors import UseCaseError
from ..composition import meeting_service, share_notifications

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
async def world(
    settings: DatabaseSettings, *, member_granted: bool = False
) -> AsyncGenerator[World]:
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
            session.add_all(
                MeetingAccessGrant(meeting_id=meeting, user_id=recipient, granted_by_user_id=owner)
                for recipient in ([moderator, member] if member_granted else [moderator])
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
    directory = WorkspaceMembershipService(memberships)
    now = datetime.now(UTC)
    members = MemberService(
        MemberRepository(session),
        directory,
        MemberAccessRelease(AccessRepository(session), MeetingRepository(session)),
        AuditWriter(session),
    )
    if operation == "remove":
        await members.remove(place.owner, place.workspace, place.member, now)
    elif operation == "grant":
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
            place.moderator, place.meeting, {place.moderator, place.member}, now, restricted=True
        )
    else:
        actor, target, role = {
            "demote": (place.moderator, place.moderator, InvitationRole.MEMBER),
            "dismiss": (place.owner, place.moderator, InvitationRole.MEMBER),
            "promote": (place.moderator, place.member, InvitationRole.MODERATOR),
        }[operation]
        await members.change_role(actor, place.workspace, target, role, now)


async def _serialized(place: World, first: str, second: str) -> list[str]:
    """Run `first` and keep it uncommitted until `second` reaches the membership locks."""
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
        except DBAPIError as error:
            return f"{operation}: {type(error.orig).__name__}"
        return f"{operation}: done"

    return sorted(
        await asyncio.wait_for(asyncio.gather(perform(first), perform(second)), timeout=20)
    )


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
            # Act
            return await _serialized(place, first, "promote" if first == "dismiss" else "dismiss")

    results = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)

    # Assert
    assert results == expected


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
            # Act
            results = await _serialized(place, first, "grant" if first == "remove" else "remove")
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
                            WorkspaceMembership.user_id == place.member,
                        )
                    )
                    is not None
                )
                return results, granted, still_member, {place.moderator}

    results, granted, still_member, recipients = asyncio.run(
        scenario(), loop_factory=asyncio.SelectorEventLoop
    )

    # Assert
    assert (results, granted, still_member) == (expected, recipients, False)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param("grant", id="a-recipient-changes-the-access"),
        pytest.param("demote", id="a-recipient-demotes-themselves"),
        pytest.param("remove", id="a-recipient-is-removed"),
    ],
)
def test_membership_and_access_changes_wait_for_a_concurrent_move(
    database_settings: DatabaseSettings, operation: str
) -> None:
    # Arrange
    async def scenario() -> list[str]:
        async with world(database_settings, member_granted=operation == "remove") as place:
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
                            operation,
                            ObservedMembershipRepository(session, attempted),
                        )
                except DBAPIError as error:
                    return f"{operation}: {type(error.orig).__name__}"
                return f"{operation}: done"

            # Act
            return sorted(await asyncio.wait_for(asyncio.gather(move(), change()), timeout=20))

    results = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)

    # Assert
    assert results == sorted(["move: done", f"{operation}: done"])
