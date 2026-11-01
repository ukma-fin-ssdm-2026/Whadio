import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import override
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import WorkspaceRole
from ...accounts.models import Invitation, User, Workspace, WorkspaceMembership
from ...accounts.redemption import RedemptionService
from ...accounts.redemption_repository import InvitationLink, RedemptionRepository
from ...accounts.repositories import (
    InvitationRepository,
    MembershipRepository,
    RegistrationRepository,
    SessionRepository,
)
from ...accounts.services import InvitationService, RegistrationDetails, WorkspaceMembershipService
from ...audit.enums import AuditAction
from ...audit.models import AuditEvent
from ...audit.services import AuditWriter
from ...shared.database import (
    Database,
    DatabaseSettings,
    MigrationSettings,
    create_migration_engine,
)
from ...shared.errors import UseCaseError
from ..composition import invitation_service, redemption_service, registration_service
from .test_routes_redemption import PASSWORD, issue

pytestmark = pytest.mark.slow
DETAILS = RegistrationDetails("New member", PASSWORD, accept_terms=True)


@dataclass(frozen=True)
class World:
    database: Database
    owner: UUID
    workspace: UUID
    invitation: UUID
    token: str
    email: str
    invitee: UUID


@asynccontextmanager
async def world(settings: DatabaseSettings, *, existing: bool = False) -> AsyncGenerator[World]:
    database = Database(settings)
    owner: UUID | None = None
    email = f"{uuid4()}@example.com"
    try:
        async with database.transaction() as session:
            invitee = (
                await AsyncDatabase.add_account(session, PASSWORD, email) if existing else None
            )
            async with AsyncDatabase.api_client(session) as client:
                owner, invitation_id, token = await issue(client, session, email)
            invitation = await session.get(Invitation, invitation_id)
            assert invitation is not None
            place = World(
                database,
                owner,
                invitation.workspace_id,
                invitation_id,
                token,
                email,
                uuid4() if invitee is None else invitee.user_id,
            )
        yield place
    finally:
        await database.close()

        def cleanup() -> None:
            engine = create_migration_engine(
                MigrationSettings.model_validate(
                    {
                        "host": settings.host,
                        "port": settings.port,
                        "name": settings.name,
                    }
                )
            )
            try:
                with engine.begin() as connection:
                    users = select(User.user_id).where(
                        (User.email == email) | (User.user_id == owner)
                    )
                    workspaces = select(WorkspaceMembership.workspace_id).where(
                        WorkspaceMembership.user_id.in_(users),
                        WorkspaceMembership.role == WorkspaceRole.OWNER,
                    )
                    # Only the owner role may remove the audit rows from committed test fixtures.
                    connection.execute(
                        delete(AuditEvent).where(AuditEvent.actor_user_id.in_(users))
                    )
                    connection.execute(
                        delete(Workspace).where(Workspace.workspace_id.in_(workspaces))
                    )
                    connection.execute(delete(User).where(User.user_id.in_(users)))
            finally:
                engine.dispose()

        await asyncio.to_thread(cleanup)


class RendezvousRepository(RedemptionRepository):
    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier: asyncio.Barrier = barrier
        self._seen: bool = False

    @override
    async def find(self, invitation_id: UUID) -> InvitationLink | None:
        found = await super().find(invitation_id)
        if not self._seen:
            self._seen = True
            await self._barrier.wait()
        return found


def service(session: AsyncSession, repository: RedemptionRepository) -> RedemptionService:
    return RedemptionService(
        repository,
        RegistrationRepository(session),
        SessionRepository(session),
        registration_service(session),
        AuditWriter(session),
    )


async def redeem(place: World, operation: str, barrier: asyncio.Barrier) -> str:
    try:
        async with place.database.transaction() as session:
            unit = service(session, RendezvousRepository(session, barrier))
            now = datetime.now(UTC)
            if operation == "register":
                await unit.register(place.invitation, place.token, DETAILS, now)
            else:
                await unit.accept(place.invitation, place.token, place.invitee, place.email, now)
    except UseCaseError as error:
        return error.code.value
    return operation


@pytest.mark.parametrize("operation", ["register", "accept"])
def test_concurrent_redemptions_join_and_audit_once(
    database_settings: DatabaseSettings, operation: str
) -> None:
    # Arrange
    async def scenario() -> tuple[list[str], int, int, int]:
        async with world(database_settings, existing=operation == "accept") as place:
            barrier = asyncio.Barrier(2)
            # Act
            results = await asyncio.wait_for(
                asyncio.gather(
                    redeem(place, operation, barrier),
                    redeem(place, operation, barrier),
                ),
                timeout=20,
            )
            async with place.database.transaction() as session:
                members = await session.scalar(
                    select(func.count())
                    .select_from(WorkspaceMembership)
                    .where(
                        WorkspaceMembership.workspace_id == place.workspace,
                        WorkspaceMembership.user_id != place.owner,
                    )
                )
                audits = await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == place.workspace,
                        AuditEvent.action == AuditAction.MEMBER_JOINED,
                    )
                )
                accounts = await session.scalar(
                    select(func.count()).select_from(User).where(User.email == place.email)
                )
                return sorted(results), members or 0, audits or 0, accounts or 0

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == (
        ["LINK_INVALID", "register"] if operation == "register" else ["accept", "accept"],
        1,
        1,
        1,
    )


class ObservedRedemptionRepository(RedemptionRepository):
    def __init__(self, session: AsyncSession, attempted: asyncio.Event) -> None:
        super().__init__(session)
        self._attempted: asyncio.Event = attempted

    @override
    async def lock(self, invitation_id: UUID) -> Invitation | None:
        self._attempted.set()
        return await super().lock(invitation_id)


class ObservedMembershipRepository(MembershipRepository):
    def __init__(self, session: AsyncSession, attempted: asyncio.Event) -> None:
        super().__init__(session)
        self._attempted: asyncio.Event = attempted

    @override
    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        self._attempted.set()
        return await super().lock_role(workspace_id, user_id)


@pytest.mark.parametrize("winner", ["register", "cancel"])
def test_register_and_cancel_serialize_without_partial_account_creation(
    database_settings: DatabaseSettings, winner: str
) -> None:
    # Arrange
    async def scenario() -> tuple[list[str], int]:
        async with world(database_settings) as place:
            completed, attempted = asyncio.Event(), asyncio.Event()

            async def perform(operation: str, *, first: bool) -> str:
                if not first:
                    await completed.wait()
                try:
                    async with place.database.transaction() as session:
                        now = datetime.now(UTC)
                        if operation == "register":
                            unit = (
                                redemption_service(session, registration_service(session))
                                if first
                                else service(
                                    session, ObservedRedemptionRepository(session, attempted)
                                )
                            )
                            await unit.register(place.invitation, place.token, DETAILS, now)
                        else:
                            invitations = (
                                invitation_service(session)
                                if first
                                else InvitationService(
                                    InvitationRepository(session),
                                    WorkspaceMembershipService(
                                        ObservedMembershipRepository(session, attempted)
                                    ),
                                    AuditWriter(session),
                                )
                            )
                            await invitations.cancel(
                                place.owner, place.workspace, place.invitation, now
                            )
                        if first:
                            completed.set()
                            await attempted.wait()
                except UseCaseError as error:
                    return error.code.value
                return operation

            # Act
            results = await asyncio.wait_for(
                asyncio.gather(
                    perform(winner, first=True),
                    perform("cancel" if winner == "register" else "register", first=False),
                ),
                timeout=20,
            )
            async with place.database.transaction() as session:
                count = await session.scalar(
                    select(func.count()).select_from(User).where(User.email == place.email)
                )
                return sorted(results), count or 0

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == (
        (["INVITATION_NOT_PENDING", "register"], 1)
        if winner == "register"
        else (["LINK_INVALID", "cancel"], 0)
    )


@pytest.mark.parametrize("operation", ["preview", "accept", "decline", "register"])
def test_wrong_token_does_not_wait_for_workspace_lock(
    database_settings: DatabaseSettings, operation: str
) -> None:
    # Arrange
    async def scenario() -> str:
        async with world(database_settings) as place, place.database.transaction() as held:
            await held.scalar(
                select(Workspace).where(Workspace.workspace_id == place.workspace).with_for_update()
            )
            # Act
            try:
                async with place.database.transaction() as session:
                    unit = redemption_service(session, registration_service(session))
                    now = datetime.now(UTC)
                    async with asyncio.timeout(3):
                        if operation == "preview":
                            await unit.preview(place.invitation, "wrong", now)
                        elif operation == "accept":
                            await unit.accept(
                                place.invitation, "wrong", place.invitee, place.email, now
                            )
                        elif operation == "decline":
                            await unit.decline(place.invitation, "wrong", now)
                        else:
                            await unit.register(place.invitation, "wrong", DETAILS, now)
            except UseCaseError as error:
                return error.code.value
            return "unexpected-success"

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == "LINK_INVALID"


def test_preview_does_not_wait_for_workspace_lock(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> str:
        async with world(database_settings) as place, place.database.transaction() as held:
            await held.scalar(
                select(Workspace).where(Workspace.workspace_id == place.workspace).with_for_update()
            )
            # Act
            async with place.database.transaction() as session, asyncio.timeout(3):
                found = await redemption_service(session, registration_service(session)).preview(
                    place.invitation, place.token, datetime.now(UTC)
                )
                return found.invitation.invited_email

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result.endswith("@example.com")


def test_open_preview_does_not_block_workspace_foreign_key_lock(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> UUID | None:
        async with world(database_settings) as place, place.database.transaction() as preview:
            await redemption_service(preview, registration_service(preview)).preview(
                place.invitation, place.token, datetime.now(UTC)
            )
            # Act
            async with place.database.transaction() as insert, asyncio.timeout(3):
                return await insert.scalar(
                    select(Workspace.workspace_id)
                    .where(Workspace.workspace_id == place.workspace)
                    .with_for_update(read=True, key_share=True)
                )

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result is not None


class PausedRepository(RedemptionRepository):
    def __init__(self, session: AsyncSession, ready: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(session)
        self._ready: asyncio.Event = ready
        self._release: asyncio.Event = release

    @override
    async def lock(self, invitation_id: UUID) -> Invitation | None:
        self._ready.set()
        await self._release.wait()
        return await super().lock(invitation_id)


@pytest.mark.parametrize("change", ["cancel", "rotate"])
def test_write_rechecks_link_changed_after_unlocked_read(
    database_settings: DatabaseSettings, change: str
) -> None:
    # Arrange
    async def scenario() -> str:
        async with world(database_settings) as place:
            ready, release = asyncio.Event(), asyncio.Event()

            async def register() -> str:
                try:
                    async with place.database.transaction() as session:
                        await service(session, PausedRepository(session, ready, release)).register(
                            place.invitation, place.token, DETAILS, datetime.now(UTC)
                        )
                except UseCaseError as error:
                    return error.code.value
                return "registered"

            async def alter() -> None:
                await ready.wait()
                async with place.database.transaction() as session:
                    invitation = await session.get(Invitation, place.invitation)
                    assert invitation is not None
                    if change == "cancel":
                        await invitation_service(session).cancel(
                            place.owner, place.workspace, place.invitation, datetime.now(UTC)
                        )
                    else:
                        invitation.token_hash = uuid4().hex
                release.set()

            # Act
            result, _ = await asyncio.wait_for(asyncio.gather(register(), alter()), timeout=20)
            return result

    result = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result == "LINK_INVALID"
