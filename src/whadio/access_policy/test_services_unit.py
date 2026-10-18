import asyncio
import hashlib
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select

from ..accounts.contracts import UserProfile
from ..accounts.enums import WorkspaceRole
from ..audit.enums import AuditAction
from ..audit.fakes import RecordingAuditWriter
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .contracts import MeetingScope
from .models import ExternalShare, MeetingAccessGrant, ShareAccessRequest
from .services import AccessCollaborators, AccessService, ContentPath
from .test_services import FakeMeetings, FakeNotices

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


class FakeAccessRepository:
    def __init__(self) -> None:
        self.grant_rows: dict[UUID, list[MeetingAccessGrant]] = {}
        self.share_rows: dict[UUID, ExternalShare] = {}
        self.request_rows: dict[UUID, ShareAccessRequest] = {}

    async def recipient_shares(self, user_id: UUID, page: ListWindow) -> list[ExternalShare]:
        return [
            share
            for share in self.share_rows.values()
            if share.recipient_user_id == user_id and share.revoked_at is None
        ][: page.limit]

    async def shares(self, meeting_id: UUID, page: ListWindow | None = None) -> list[ExternalShare]:
        found = [share for share in self.share_rows.values() if share.meeting_id == meeting_id]
        return found if page is None else found[: page.limit]

    async def requests(
        self, share_id: UUID, page: ListWindow | None = None
    ) -> list[ShareAccessRequest]:
        found = [request for request in self.request_rows.values() if request.share_id == share_id]
        return found if page is None else found[: page.limit]

    def granted_meetings(self, user_id: UUID) -> Select[UUID]:
        raise NotImplementedError(user_id)

    async def grants(self, meeting_id: UUID) -> set[UUID]:
        return {grant.user_id for grant in self.grant_rows.get(meeting_id, [])}

    async def replace_grants(self, meeting_id: UUID, grants: list[MeetingAccessGrant]) -> None:
        self.grant_rows[meeting_id] = grants

    async def share(self, share_id: UUID, *, lock: bool = False) -> ExternalShare | None:
        del lock
        return self.share_rows.get(share_id)

    async def request(self, request_id: UUID) -> ShareAccessRequest | None:
        return self.request_rows.get(request_id)

    async def requested(self, share_id: UUID, user_id: UUID) -> bool:
        return any(
            request.share_id == share_id and request.requester_user_id == user_id
            for request in self.request_rows.values()
        )

    async def save_share(self, share: ExternalShare) -> None:
        self.share_rows[share.share_id] = share

    async def save_request(self, request: ShareAccessRequest) -> None:
        self.request_rows[request.share_access_request_id] = request


class FakeDirectory:
    def __init__(self) -> None:
        self.roles: dict[tuple[UUID, UUID], WorkspaceRole] = {}
        self.profiles: dict[UUID, UserProfile] = {}

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return self.roles.get((workspace_id, user_id))

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return self.roles.get((workspace_id, user_id))

    async def members(self, workspace_id: UUID) -> list[UUID]:
        return [user_id for (workspace, user_id) in self.roles if workspace == workspace_id]

    async def profile(self, user_id: UUID) -> UserProfile | None:
        return self.profiles.get(user_id)

    async def workspaces(self, user_id: UUID) -> list[UUID]:
        return [workspace for (workspace, member) in self.roles if member == user_id]


@dataclass(frozen=True)
class World:
    access: AccessService
    repository: FakeAccessRepository
    directory: FakeDirectory
    audit: RecordingAuditWriter
    notices: FakeNotices
    owner: UUID
    member: UUID
    outsider: UUID
    meeting: UUID


def world() -> World:
    owner, member, outsider, workspace, meeting = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    repository, directory = FakeAccessRepository(), FakeDirectory()
    meetings, audit, notices = FakeMeetings(), RecordingAuditWriter(), FakeNotices()
    directory.roles[workspace, owner] = WorkspaceRole.OWNER
    directory.roles[workspace, member] = WorkspaceRole.MEMBER
    directory.profiles[owner] = UserProfile("Olena", "olena@example.test")
    directory.profiles[member] = UserProfile("Mark", "mark@example.test")
    directory.profiles[outsider] = UserProfile("Oksana", "oksana@example.test")
    meetings.scopes[meeting] = MeetingScope(meeting, workspace, owner, restricted=False)
    access = AccessService(AccessCollaborators(repository, meetings, directory, audit, notices))
    return World(access, repository, directory, audit, notices, owner, member, outsider, meeting)


def refusal(call: Awaitable[object]) -> Failure | None:
    async def attempt() -> Failure | None:
        try:
            await call
        except UseCaseError as error:
            return error.code
        return None

    return asyncio.run(attempt())


def shared_with_outsider(unit: World) -> ShareAccessRequest:
    async def scenario() -> ShareAccessRequest:
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        return await unit.access.request_access(
            unit.outsider, created.share.share_id, created.token, NOW
        )

    return asyncio.run(scenario())


# --- Reading a meeting ---


def test_nonmember_cannot_see_the_meeting() -> None:
    # Arrange
    unit = world()
    # Act
    failure = refusal(unit.access.read_access(unit.outsider, unit.meeting))
    # Assert
    assert failure is Failure.NOT_FOUND


def test_restricted_meeting_is_missing_for_a_member_without_a_grant() -> None:
    # Arrange
    unit = world()
    asyncio.run(
        unit.access.replace_access(unit.owner, unit.meeting, {unit.owner}, NOW, restricted=True)
    )
    # Act
    failure = refusal(unit.access.read_access(unit.member, unit.meeting))
    # Assert
    assert failure is Failure.NOT_FOUND


# --- Restricting a meeting ---


def test_member_cannot_restrict_a_meeting() -> None:
    # Arrange
    unit = world()
    # Act
    failure = refusal(
        unit.access.replace_access(unit.member, unit.meeting, {unit.member}, NOW, restricted=True)
    )
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_meeting_cannot_be_restricted_to_a_nonmember() -> None:
    # Arrange
    unit = world()
    # Act
    failure = refusal(
        unit.access.replace_access(unit.owner, unit.meeting, {unit.outsider}, NOW, restricted=True)
    )
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_restricting_a_meeting_audits_the_restriction_and_each_grant() -> None:
    # Arrange
    unit = world()
    # Act
    asyncio.run(
        unit.access.replace_access(unit.owner, unit.meeting, {unit.member}, NOW, restricted=True)
    )
    # Assert
    assert [(event.action, event.subject_id) for event in unit.audit.events] == [
        (AuditAction.MEETING_RESTRICTED, None),
        (AuditAction.ACCESS_GRANTED, unit.member),
    ]


# --- Shares ---


def test_share_stores_only_a_hash_of_its_token() -> None:
    # Arrange
    unit = world()
    # Act
    created = asyncio.run(unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False))
    # Assert
    assert created.share.token_hash == hashlib.sha256(created.token.encode()).hexdigest()


def test_access_request_with_a_wrong_token_is_refused() -> None:
    # Arrange
    unit = world()
    created = asyncio.run(unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False))
    # Act
    failure = refusal(
        unit.access.request_access(unit.outsider, created.share.share_id, "wrong", NOW)
    )
    # Assert
    assert failure is Failure.LINK_INVALID


def test_member_who_can_read_the_meeting_cannot_request_access() -> None:
    # Arrange
    unit = world()
    created = asyncio.run(unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False))
    # Act
    failure = refusal(
        unit.access.request_access(unit.member, created.share.share_id, created.token, NOW)
    )
    # Assert
    assert failure is Failure.ALREADY_HAS_ACCESS


def test_second_access_request_for_the_same_share_is_refused() -> None:
    # Arrange
    unit = world()
    created = asyncio.run(unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False))
    asyncio.run(
        unit.access.request_access(unit.outsider, created.share.share_id, created.token, NOW)
    )
    # Act
    failure = refusal(
        unit.access.request_access(unit.outsider, created.share.share_id, created.token, NOW)
    )
    # Assert
    assert failure is Failure.ACCESS_REQUEST_EXISTS


def test_access_request_notifies_the_share_creator() -> None:
    # Arrange
    unit = world()
    # Act
    request = shared_with_outsider(unit)
    # Assert
    assert unit.notices.sent == [(request.share_id, unit.owner, unit.outsider)]


def test_approving_a_request_binds_the_share_to_the_requester() -> None:
    # Arrange
    unit = world()
    request = shared_with_outsider(unit)
    # Act
    asyncio.run(unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True))
    # Assert
    assert unit.repository.share_rows[request.share_id].recipient_user_id == unit.outsider


def test_share_recipient_cannot_export_the_meeting() -> None:
    # Arrange
    unit = world()
    request = shared_with_outsider(unit)
    asyncio.run(unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True))
    # Act
    failure = refusal(
        unit.access.policy.authorize_share(request.share_id, unit.outsider, ContentPath.EXPORT)
    )
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_revoked_share_is_refused_to_its_recipient() -> None:
    # Arrange
    unit = world()
    request = shared_with_outsider(unit)
    asyncio.run(unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True))
    asyncio.run(unit.access.revoke(unit.owner, request.share_id, NOW))
    # Act
    failure = refusal(
        unit.access.policy.authorize_share(request.share_id, unit.outsider, ContentPath.READ)
    )
    # Assert
    assert failure is Failure.SHARE_REVOKED


def test_revoking_a_share_twice_audits_it_once() -> None:
    # Arrange
    unit = world()
    created = asyncio.run(unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False))
    asyncio.run(unit.access.revoke(unit.owner, created.share.share_id, NOW))
    # Act
    asyncio.run(unit.access.revoke(unit.owner, created.share.share_id, NOW))
    # Assert
    assert [event.action for event in unit.audit.events].count(AuditAction.SHARE_REVOKED) == 1


# --- Requester profiles ---


def test_creator_sees_the_requesters_own_profile() -> None:
    # Arrange
    unit = world()
    request = shared_with_outsider(unit)
    # Act
    profile = asyncio.run(
        unit.access.requester_profile(unit.owner, request.share_access_request_id)
    )
    # Assert
    assert profile == UserProfile("Oksana", "oksana@example.test")


def test_other_member_cannot_see_the_requester_profile() -> None:
    # Arrange
    unit = world()
    request = shared_with_outsider(unit)
    # Act
    failure = refusal(unit.access.requester_profile(unit.member, request.share_access_request_id))
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE
