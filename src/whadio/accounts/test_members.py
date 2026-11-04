import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..audit.services import MemberRoleChanged
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .enums import InvitationRole, WorkspaceRole
from .member_repository import MemberRepository, WorkspaceMember
from .members import MemberService
from .repositories import MembershipRepository
from .services import WorkspaceMembershipService
from .test_member_repository import add_member, add_workspace

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
WORKSPACE = uuid4()
ACTOR = uuid4()


def _member(role: WorkspaceRole, user_id: UUID | None = None) -> WorkspaceMember:
    return WorkspaceMember(user_id or uuid4(), "Bob", "bob@example.com", role, NOW)


class Members:
    def __init__(self, *members: WorkspaceMember) -> None:
        self.members: list[WorkspaceMember] = list(members)
        self.roles_set: list[tuple[UUID, WorkspaceRole]] = []

    async def page(self, workspace_id: UUID, page: ListWindow) -> list[WorkspaceMember]:
        del workspace_id, page
        return self.members

    async def find(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        del workspace_id
        return next((item for item in self.members if item.user_id == user_id), None)

    async def set_role(self, workspace_id: UUID, user_id: UUID, role: WorkspaceRole) -> None:
        del workspace_id
        self.roles_set.append((user_id, role))


class Memberships:
    def __init__(self, role: WorkspaceRole | None) -> None:
        self.role_value: WorkspaceRole | None = role

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value


class Audit:
    def __init__(self) -> None:
        self.events: list[MemberRoleChanged] = []

    async def write(self, event: MemberRoleChanged) -> None:
        self.events.append(event)


def _service(
    actor_role: WorkspaceRole | None, *members: WorkspaceMember, audit: Audit | None = None
) -> MemberService:
    return MemberService(Members(*members), Memberships(actor_role), audit or Audit())


def _refusal(call: Awaitable[object]) -> Failure:
    async def scenario() -> None:
        await call

    with pytest.raises(UseCaseError) as failure:
        asyncio.run(scenario())
    return failure.value.code


# --- Listing ---


def test_outsider_is_told_the_member_list_is_missing() -> None:
    # Arrange
    service = _service(None)

    # Act
    refused = _refusal(service.list(ACTOR, WORKSPACE, ListWindow(21)))

    # Assert
    assert refused is Failure.NOT_FOUND


def test_plain_member_lists_the_members() -> None:
    # Arrange
    member = _member(WorkspaceRole.MEMBER)
    service = _service(WorkspaceRole.MEMBER, member)

    # Act
    found = asyncio.run(service.list(ACTOR, WORKSPACE, ListWindow(21)))

    # Assert
    assert found == [member]


# --- Changing a role ---


@pytest.mark.parametrize(
    ("actor_role", "target_role", "expected"),
    [
        pytest.param(None, WorkspaceRole.MEMBER, Failure.NOT_FOUND, id="outsider"),
        pytest.param(
            WorkspaceRole.MEMBER,
            WorkspaceRole.OWNER,
            Failure.INSUFFICIENT_ROLE,
            id="member-refused-before-the-owner-check",
        ),
        pytest.param(WorkspaceRole.OWNER, None, Failure.NOT_FOUND, id="unknown-member"),
        pytest.param(
            WorkspaceRole.MODERATOR, WorkspaceRole.OWNER, Failure.OWNER_IMMUTABLE, id="owner"
        ),
    ],
)
def test_role_change_is_refused(
    actor_role: WorkspaceRole | None, target_role: WorkspaceRole | None, expected: Failure
) -> None:
    # Arrange
    target = _member(target_role or WorkspaceRole.MEMBER)
    service = _service(actor_role, *([target] if target_role is not None else []))

    # Act
    refused = _refusal(
        service.change_role(ACTOR, WORKSPACE, target.user_id, InvitationRole.MODERATOR, NOW)
    )

    # Assert
    assert refused is expected


def test_moderator_demotes_another_moderator() -> None:
    # Arrange
    moderator = _member(WorkspaceRole.MODERATOR)
    members = Members(moderator)
    service = MemberService(members, Memberships(WorkspaceRole.MODERATOR), Audit())

    # Act
    asyncio.run(
        service.change_role(ACTOR, WORKSPACE, moderator.user_id, InvitationRole.MEMBER, NOW)
    )

    # Assert
    assert members.roles_set == [(moderator.user_id, WorkspaceRole.MEMBER)]


def test_moderator_demotes_themselves() -> None:
    # Arrange
    service = _service(WorkspaceRole.MODERATOR, _member(WorkspaceRole.MODERATOR, ACTOR))

    # Act
    changed = asyncio.run(service.change_role(ACTOR, WORKSPACE, ACTOR, InvitationRole.MEMBER, NOW))

    # Assert
    assert changed.role is WorkspaceRole.MEMBER


def test_role_change_is_audited_with_the_old_and_new_role() -> None:
    # Arrange
    member = _member(WorkspaceRole.MEMBER)
    audit = Audit()
    service = _service(WorkspaceRole.OWNER, member, audit=audit)

    # Act
    asyncio.run(
        service.change_role(ACTOR, WORKSPACE, member.user_id, InvitationRole.MODERATOR, NOW)
    )

    # Assert
    assert audit.events == [
        MemberRoleChanged(ACTOR, WORKSPACE, member.user_id, "Member", "Moderator", NOW)
    ]


def test_giving_the_role_a_member_has_changes_and_records_nothing() -> None:
    # Arrange
    member = _member(WorkspaceRole.MODERATOR)
    members, audit = Members(member), Audit()
    service = MemberService(members, Memberships(WorkspaceRole.OWNER), audit)

    # Act
    unchanged = asyncio.run(
        service.change_role(ACTOR, WORKSPACE, member.user_id, InvitationRole.MODERATOR, NOW)
    )

    # Assert
    assert (unchanged, members.roles_set, audit.events) == (member, [], [])


class FailingAudit:
    async def write(self, event: MemberRoleChanged) -> None:
        raise RuntimeError(f"Audit unavailable for {event.member_id}")


@pytest.mark.slow
def test_failed_audit_leaves_the_role_unchanged(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> WorkspaceRole | None:
        workspace = await add_workspace(session)
        owner = await add_member(session, workspace, NOW, role=WorkspaceRole.OWNER)
        member = await add_member(session, workspace, NOW)
        repository = MemberRepository(session)
        service = MemberService(
            repository, WorkspaceMembershipService(MembershipRepository(session)), FailingAudit()
        )
        # Act
        with pytest.raises(RuntimeError, match="Audit unavailable"):
            async with session.begin_nested():
                await service.change_role(
                    owner.user_id, workspace, member.user_id, InvitationRole.MODERATOR, NOW
                )
        found = await repository.find(workspace, member.user_id)
        return None if found is None else found.role

    # Assert
    assert async_database.run(scenario) is WorkspaceRole.MEMBER
