from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..audit.enums import AuditAction
from ..audit.models import AuditEvent
from ..audit.services import AuditWriter
from ..shared.errors import Failure, UseCaseError
from .enums import NotesTemplate, SessionKind, WorkspaceRole
from .models import PendingRegistration, Session, User, Workspace, WorkspaceMembership
from .passwords import Argon2PasswordHasher
from .repositories import (
    IdentityRepository,
    MembershipRepository,
    RegistrationRepository,
    SessionRepository,
    WorkspaceRepository,
)
from .services import (
    IdentityService,
    RegistrationDetails,
    RegistrationIssuer,
    RegistrationLink,
    RegistrationService,
    RegistrationValidationError,
    SignInService,
    WorkspaceMembershipService,
    WorkspaceService,
)

pytestmark = pytest.mark.slow

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
PASSWORD = uuid4().hex
REGISTRATION_DETAILS = RegistrationDetails("Alice", f"A1{uuid4().hex}", accept_terms=True)


async def add_member(session: AsyncSession, workspace_id: UUID, role: WorkspaceRole) -> UUID:
    member = await AsyncDatabase.add_account(session, PASSWORD)
    session.add(WorkspaceMembership(workspace_id=workspace_id, user_id=member.user_id, role=role))
    await session.flush()
    return member.user_id


async def workspace_of(session: AsyncSession, owner: UUID) -> UUID:
    found = await session.scalar(
        select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == owner)
    )
    assert found is not None
    return found


def sign_ins(session: AsyncSession) -> SignInService:
    return SignInService(SessionRepository(session), Argon2PasswordHasher())


class FakeContent:
    def __init__(self) -> None:
        self.default_folders: list[UUID] = []
        self.emptied: list[UUID] = []

    async def add_default_folder(self, workspace_id: UUID, _now: datetime) -> None:
        self.default_folders.append(workspace_id)

    async def remove_meetings(self, workspace_id: UUID, _now: datetime) -> None:
        self.emptied.append(workspace_id)


def workspaces(session: AsyncSession, content: FakeContent | None = None) -> WorkspaceService:
    return WorkspaceService(
        WorkspaceRepository(session),
        WorkspaceMembershipService(MembershipRepository(session)),
        content or FakeContent(),
        AuditWriter(session),
    )


async def refusal(call: Awaitable[object]) -> Failure | None:
    try:
        await call
    except UseCaseError as error:
        return error.code
    return None


# --- Signing in ---


def test_sign_in_starts_a_session_its_token_finds(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        signed = await sign_ins(session).sign_in(user.email, PASSWORD, SessionKind.BROWSER, NOW)
        found = await IdentityService(IdentityRepository(session)).session_user(
            signed.token, SessionKind.BROWSER, NOW + timedelta(hours=1)
        )
        return found is not None and found.user_id == user.user_id

    # Act
    found = async_database.run(scenario)
    # Assert
    assert found


def test_sign_in_finds_the_address_whatever_its_case(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(
            session, PASSWORD, f"Alice.{uuid4().hex}@Example.test"
        )
        signed = await sign_ins(session).sign_in(
            user.email.upper(), PASSWORD, SessionKind.BROWSER, NOW
        )
        return signed.user.user_id == user.user_id

    # Act
    found = async_database.run(scenario)
    # Assert
    assert found


def test_wrong_password_is_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        return await refusal(
            sign_ins(session).sign_in(user.email, "wrong", SessionKind.BROWSER, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INVALID_CREDENTIALS


def test_unknown_address_is_refused_the_same_way(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        return await refusal(
            sign_ins(session).sign_in(f"{uuid4()}@example.test", PASSWORD, SessionKind.BROWSER, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INVALID_CREDENTIALS


def test_failed_sign_in_starts_no_session(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        await refusal(sign_ins(session).sign_in(user.email, "wrong", SessionKind.BROWSER, NOW))
        return await session.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == user.user_id)
        )

    # Act
    sessions = async_database.run(scenario)
    # Assert
    assert sessions == 0


@pytest.mark.parametrize(
    ("kind", "lifetime"),
    [(SessionKind.BROWSER, timedelta(days=14)), (SessionKind.EXTENSION, timedelta(hours=24))],
)
def test_session_ends_after_its_lifetime(
    async_database: AsyncDatabase, kind: SessionKind, lifetime: timedelta
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        signed = await sign_ins(session).sign_in(user.email, PASSWORD, kind, NOW)
        identities = IdentityService(IdentityRepository(session))
        before = await identities.session_user(
            signed.token, kind, NOW + lifetime - timedelta(seconds=1)
        )
        after = await identities.session_user(signed.token, kind, NOW + lifetime)
        return before is not None, after is not None

    # Act
    found = async_database.run(scenario)
    # Assert
    assert found == (True, False)


def test_extension_token_is_not_a_browser_session(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        signed = await sign_ins(session).sign_in(user.email, PASSWORD, SessionKind.EXTENSION, NOW)
        found = await IdentityService(IdentityRepository(session)).session_user(
            signed.token, SessionKind.BROWSER, NOW
        )
        return found is None

    # Act
    refused = async_database.run(scenario)
    # Assert
    assert refused


def test_sign_in_clears_the_accounts_expired_sessions(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        await sign_ins(session).sign_in(user.email, PASSWORD, SessionKind.EXTENSION, NOW)
        await sign_ins(session).sign_in(
            user.email, PASSWORD, SessionKind.BROWSER, NOW + timedelta(days=2)
        )
        return await session.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == user.user_id)
        )

    # Act
    sessions = async_database.run(scenario)
    # Assert
    assert sessions == 1


def test_sign_out_ends_every_presented_session(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        browser = await sign_ins(session).sign_in(user.email, PASSWORD, SessionKind.BROWSER, NOW)
        extension = await sign_ins(session).sign_in(
            user.email, PASSWORD, SessionKind.EXTENSION, NOW
        )
        await sign_ins(session).sign_out([browser.token, extension.token])
        identities = IdentityService(IdentityRepository(session))
        return [
            await identities.session_user(browser.token, SessionKind.BROWSER, NOW) is None,
            await identities.session_user(extension.token, SessionKind.EXTENSION, NOW) is None,
        ]

    # Act
    ended = async_database.run(scenario)
    # Assert
    assert ended == [True, True]


def test_session_token_is_stored_only_hashed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        signed = await sign_ins(session).sign_in(user.email, PASSWORD, SessionKind.BROWSER, NOW)
        stored = await session.scalars(
            select(Session.token_hash).where(Session.user_id == user.user_id)
        )
        return signed.token in stored.all()

    # Act
    stored_plainly = async_database.run(scenario)
    # Assert
    assert not stored_plainly


# --- Workspaces ---


def test_created_workspace_has_its_creator_as_owner(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> WorkspaceRole:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        # Act
        created = await workspaces(session).create(
            user.user_id, "Product team", NotesTemplate.DETAILED, NOW
        )
        return created.role

    role = async_database.run(scenario)
    # Assert
    assert role is WorkspaceRole.OWNER


def test_created_workspace_gets_a_default_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    content = FakeContent()

    async def scenario(session: AsyncSession) -> UUID:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        # Act
        created = await workspaces(session, content).create(
            user.user_id, "Product team", NotesTemplate.DETAILED, NOW
        )
        return created.workspace_id

    workspace_id = async_database.run(scenario)
    # Assert
    assert content.default_folders == [workspace_id]


def test_workspaces_are_listed_oldest_first(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[str]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        service = workspaces(session)
        await service.create(user.user_id, "Second", NotesTemplate.SUMMARY, NOW)
        await service.create(user.user_id, "First", NotesTemplate.SUMMARY, NOW - timedelta(1))
        return [found.name for found in await service.list_workspaces(user.user_id)]

    # Act
    names = async_database.run(scenario)
    # Assert
    assert names == ["First", "Second"]


def test_workspace_of_another_member_is_missing(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        owner, outsider = (
            await AsyncDatabase.add_account(session, PASSWORD),
            await AsyncDatabase.add_account(session, PASSWORD),
        )
        created = await workspaces(session).create(
            owner.user_id, "Private", NotesTemplate.SUMMARY, NOW
        )
        return await refusal(workspaces(session).get(outsider.user_id, created.workspace_id))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


def test_owner_renames_the_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        owner = await AsyncDatabase.add_account(session, PASSWORD)
        created = await workspaces(session).create(owner.user_id, "Old", NotesTemplate.SUMMARY, NOW)
        updated = await workspaces(session).update(owner.user_id, created.workspace_id, "New", None)
        return updated.name

    # Act
    name = async_database.run(scenario)
    # Assert
    assert name == "New"


@pytest.mark.parametrize("role", [WorkspaceRole.MODERATOR, WorkspaceRole.MEMBER])
def test_only_the_owner_changes_settings(
    async_database: AsyncDatabase, role: WorkspaceRole
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        owner = await AsyncDatabase.add_account(session, PASSWORD)
        created = await workspaces(session).create(
            owner.user_id, "Team", NotesTemplate.SUMMARY, NOW
        )
        member = await add_member(session, created.workspace_id, role)
        return await refusal(
            workspaces(session).update(member, created.workspace_id, None, NotesTemplate.DETAILED)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_personal_workspace_cannot_be_deleted(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        owner = await AsyncDatabase.add_account(session, PASSWORD)
        created = await workspaces(session).create(
            owner.user_id, "Alice", NotesTemplate.SUMMARY, NOW
        )
        workspace = await session.get(Workspace, created.workspace_id)
        assert workspace is not None
        workspace.is_personal = True
        await session.flush()
        return await refusal(workspaces(session).delete(owner.user_id, created.workspace_id, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.PERSONAL_WORKSPACE


def test_member_cannot_delete_the_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        owner = await AsyncDatabase.add_account(session, PASSWORD)
        created = await workspaces(session).create(
            owner.user_id, "Team", NotesTemplate.SUMMARY, NOW
        )
        member = await add_member(session, created.workspace_id, WorkspaceRole.MODERATOR)
        return await refusal(workspaces(session).delete(member, created.workspace_id, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_deleted_workspace_is_gone(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Workspace | None:
        actor, _ = await AsyncDatabase.add_workspace(session)
        workspace_id = await workspace_of(session, actor)
        # Act
        await workspaces(session).delete(actor, workspace_id, NOW)
        return await session.get(Workspace, workspace_id)

    found = async_database.run(scenario)
    # Assert
    assert found is None


def test_deleted_workspace_has_its_meetings_removed(async_database: AsyncDatabase) -> None:
    # Arrange
    content = FakeContent()

    async def scenario(session: AsyncSession) -> UUID:
        actor, _ = await AsyncDatabase.add_workspace(session)
        workspace_id = await workspace_of(session, actor)
        # Act
        await workspaces(session, content).delete(actor, workspace_id, NOW)
        return workspace_id

    workspace_id = async_database.run(scenario)
    # Assert
    assert content.emptied == [workspace_id]


def test_deleted_workspace_is_audited(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID | None], UUID]:
        actor, _ = await AsyncDatabase.add_workspace(session)
        workspace_id = await workspace_of(session, actor)
        await workspaces(session).delete(actor, workspace_id, NOW)
        audited = await session.scalars(
            select(AuditEvent.workspace_id).where(
                AuditEvent.actor_user_id == actor,
                AuditEvent.action == AuditAction.WORKSPACE_DELETED,
            )
        )
        return list(audited), workspace_id

    # Act
    audited, workspace_id = async_database.run(scenario)
    # Assert
    assert audited == [workspace_id]


# --- Registration ---


class FailingRegistrationContent(FakeContent):
    @override
    async def add_default_folder(self, workspace_id: UUID, _now: datetime) -> None:
        del workspace_id, _now
        raise RuntimeError("Folder creation failed")


def registrations(session: AsyncSession, content: FakeContent | None = None) -> RegistrationService:
    return RegistrationService(
        RegistrationRepository(session),
        SessionRepository(session),
        Argon2PasswordHasher(),
        content or FakeContent(),
        WorkspaceRepository(session),
    )


async def issue_registration(session: AsyncSession, email: str, now: datetime) -> RegistrationLink:
    return await RegistrationIssuer(
        RegistrationRepository(session), SessionRepository(session)
    ).issue(email, now)


@pytest.mark.parametrize("offset", [timedelta(hours=24), timedelta(hours=25)])
def test_registration_expiry_includes_the_exact_boundary(
    async_database: AsyncDatabase, offset: timedelta
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure:
        now = datetime.now(UTC)
        link = await issue_registration(session, f"{uuid4()}@example.com", now)
        # Act
        with pytest.raises(UseCaseError) as failure:
            await registrations(session).complete(
                link.registration_id, link.token, REGISTRATION_DETAILS, now + offset
            )
        return failure.value.code

    # Assert
    assert async_database.run(scenario) is Failure.LINK_INVALID


def test_registration_link_works_just_before_expiry(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        now = datetime.now(UTC)
        link = await issue_registration(session, f"{uuid4()}@example.com", now)
        # Act
        signed = await registrations(session).complete(
            link.registration_id,
            link.token,
            REGISTRATION_DETAILS,
            now + timedelta(hours=24, microseconds=-1),
        )
        return signed.user.name

    # Assert
    assert async_database.run(scenario) == REGISTRATION_DETAILS.name


@pytest.mark.parametrize(
    "details",
    [
        RegistrationDetails("Alice", "weak", accept_terms=True),
        RegistrationDetails("Alice", REGISTRATION_DETAILS.password, accept_terms=False),
        RegistrationDetails("\u3164", REGISTRATION_DETAILS.password, accept_terms=True),
    ],
)
def test_registration_refuses_invalid_account_details(
    async_database: AsyncDatabase,
    details: RegistrationDetails,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        link = await issue_registration(session, f"{uuid4()}@example.com", datetime.now(UTC))
        # Act
        with pytest.raises(RegistrationValidationError):
            await registrations(session).complete(
                link.registration_id, link.token, details, datetime.now(UTC)
            )
        return await session.get(PendingRegistration, link.registration_id) is not None

    # Assert
    assert async_database.run(scenario)


def test_failed_folder_creation_rolls_back_registration(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        email = f"{uuid4()}@example.com"
        link = await issue_registration(session, email, datetime.now(UTC))
        # Act
        with pytest.raises(RuntimeError, match="Folder creation failed"):
            async with session.begin_nested():
                await registrations(session, FailingRegistrationContent()).complete(
                    link.registration_id,
                    link.token,
                    REGISTRATION_DETAILS,
                    datetime.now(UTC),
                )
        return (
            await session.get(PendingRegistration, link.registration_id) is not None,
            await session.scalar(select(User.user_id).where(User.email == email)) is None,
        )

    # Assert
    assert async_database.run(scenario) == (True, True)
