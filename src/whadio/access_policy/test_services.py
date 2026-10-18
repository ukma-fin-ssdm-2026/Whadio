from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..accounts.contracts import UserProfile
from ..accounts.enums import WorkspaceRole
from ..accounts.models import WorkspaceMembership
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.contracts import ContentEvent
from ..audit.enums import AuditAction
from ..audit.fakes import RecordingAuditWriter
from ..shared.errors import Failure, UseCaseError
from .contracts import MeetingScope
from .repositories import AccessRepository
from .services import AccessCollaborators, AccessService, ContentPath, Permission

pytestmark = pytest.mark.slow

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
PASSWORD = uuid4().hex


class FakeMeetings:
    def __init__(self) -> None:
        self.scopes: dict[UUID, MeetingScope] = {}

    async def scope(self, meeting_id: UUID, *, lock: bool = False) -> MeetingScope:
        del lock
        return self.scopes[meeting_id]

    async def set_restricted(self, meeting_id: UUID, *, restricted: bool) -> None:
        self.scopes[meeting_id] = replace(self.scopes[meeting_id], restricted=restricted)


class FakeNotices:
    def __init__(self) -> None:
        self.sent: list[tuple[UUID, UUID, UUID]] = []

    async def enqueue(self, share_id: UUID, creator_id: UUID, requester_id: UUID) -> None:
        self.sent.append((share_id, creator_id, requester_id))


@dataclass(frozen=True)
class World:
    access: AccessService
    meetings: FakeMeetings
    audit: RecordingAuditWriter
    notices: FakeNotices
    owner: UUID
    member: UUID
    outsider: UUID
    workspace: UUID
    meeting: UUID


async def world(session: AsyncSession) -> World:
    owner, folder = await AsyncDatabase.add_workspace(session)
    workspace = await session.scalar(
        select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == owner)
    )
    assert workspace is not None
    meeting = await AsyncDatabase.add_meeting(session, (owner, folder))
    member = (
        await AsyncDatabase.add_account(session, PASSWORD, "mark@example.com", "Mark")
    ).user_id
    outsider = (
        await AsyncDatabase.add_account(session, PASSWORD, "oksana@example.com", "Oksana")
    ).user_id
    session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=member, role=WorkspaceRole.MEMBER)
    )
    await session.flush()
    meetings, audit, notices = FakeMeetings(), RecordingAuditWriter(), FakeNotices()
    meetings.scopes[meeting] = MeetingScope(meeting, workspace, owner, restricted=False)
    access = AccessService(
        AccessCollaborators(
            AccessRepository(session),
            meetings,
            WorkspaceMembershipService(MembershipRepository(session)),
            audit,
            notices,
        )
    )
    return World(access, meetings, audit, notices, owner, member, outsider, workspace, meeting)


async def refusal(call: Awaitable[object]) -> Failure | None:
    try:
        await call
    except UseCaseError as error:
        return error.code
    return None


# --- Reading a meeting ---


def test_nonmember_cannot_see_the_meeting(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(unit.access.read_access(unit.outsider, unit.meeting))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


def test_restricted_meeting_is_missing_for_a_member_without_a_grant(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.owner}, NOW, restricted=True
        )
        return await refusal(unit.access.read_access(unit.member, unit.meeting))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


def test_read_access_lists_the_granted_members(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[tuple[bool, set[UUID]], UUID]:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.member}, NOW, restricted=True
        )
        return await unit.access.read_access(unit.member, unit.meeting), unit.member

    # Act
    found, member = async_database.run(scenario)
    # Assert
    assert found == (True, {member})


def test_restricted_recipients_are_only_the_granted_members(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], UUID]:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.member}, NOW, restricted=True
        )
        scope = await unit.meetings.scope(unit.meeting)
        return await unit.access.policy.recipients(scope), unit.member

    # Act
    recipients, member = async_database.run(scenario)
    # Assert
    assert recipients == [member]


# --- Restricting a meeting ---


def test_member_cannot_restrict_a_meeting(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(
            unit.access.replace_access(
                unit.member, unit.meeting, {unit.member}, NOW, restricted=True
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


@pytest.mark.parametrize(
    "restricted", [True, False], ids=["restricted-to-nobody", "open-with-members"]
)
def test_access_list_must_match_the_access_mode(
    async_database: AsyncDatabase, *, restricted: bool
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        members = set[UUID]() if restricted else {unit.member}
        return await refusal(
            unit.access.replace_access(
                unit.owner, unit.meeting, members, NOW, restricted=restricted
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_access_cannot_be_granted_to_a_nonmember(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(
            unit.access.replace_access(
                unit.owner, unit.meeting, {unit.outsider}, NOW, restricted=True
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_restricting_audits_the_restriction_and_each_grant(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.member}, NOW, restricted=True
        )
        return [(event.action, event.subject_id) for event in unit.audit.events] == [
            (AuditAction.MEETING_RESTRICTED, None),
            (AuditAction.ACCESS_GRANTED, unit.member),
        ]

    # Act
    matches = async_database.run(scenario)
    # Assert
    assert matches


def test_replacing_the_access_list_audits_the_removed_member(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[ContentEvent], UUID]:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.owner, unit.member}, NOW, restricted=True
        )
        unit.audit.events.clear()
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.owner}, NOW, restricted=True
        )
        return unit.audit.events, unit.member

    # Act
    events, member = async_database.run(scenario)
    # Assert
    assert (AuditAction.ACCESS_REVOKED, member) in [
        (event.action, event.subject_id) for event in events
    ]


def test_opening_a_restricted_meeting_audits_only_the_unrestriction(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[AuditAction]:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.owner}, NOW, restricted=True
        )
        unit.audit.events.clear()
        await unit.access.replace_access(unit.owner, unit.meeting, set(), NOW, restricted=False)
        return [event.action for event in unit.audit.events]

    # Act
    actions = async_database.run(scenario)
    # Assert
    assert actions == [AuditAction.MEETING_UNRESTRICTED]


# --- External shares ---


def test_outsider_with_the_link_may_request_access(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        return await refusal(
            unit.access.request_access(unit.outsider, created.share.share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is None


def test_share_creation_is_audited(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[tuple[AuditAction, UUID | None]], UUID]:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=True)
        return (
            [(event.action, event.subject_id) for event in unit.audit.events],
            created.share.share_id,
        )

    # Act
    events, share_id = async_database.run(scenario)
    # Assert
    assert events == [(AuditAction.SHARE_CREATED, share_id)]


def test_wrong_token_is_an_invalid_link(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        return await refusal(
            unit.access.request_access(unit.outsider, created.share.share_id, "wrong", NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.LINK_INVALID


def test_revoked_share_is_an_invalid_link(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        await unit.access.revoke(unit.owner, created.share.share_id, NOW)
        return await refusal(
            unit.access.request_access(unit.outsider, created.share.share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.LINK_INVALID


def test_member_of_an_open_meeting_already_has_access(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        return await refusal(
            unit.access.request_access(unit.member, created.share.share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.ALREADY_HAS_ACCESS


def test_member_without_a_grant_may_request_a_restricted_meeting(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        await unit.access.replace_access(
            unit.owner, unit.meeting, {unit.owner}, NOW, restricted=True
        )
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        return await refusal(
            unit.access.request_access(unit.member, created.share.share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is None


def test_second_request_for_the_same_share_is_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        return await refusal(
            unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.ACCESS_REQUEST_EXISTS


def test_request_notifies_the_share_creator(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        return unit.notices.sent == [(share_id, unit.owner, unit.outsider)]

    # Act
    notified = async_database.run(scenario)
    # Assert
    assert notified


def test_approved_requester_reads_through_the_share(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=True)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        permission = await unit.access.policy.authorize_share(
            share_id, unit.outsider, ContentPath.READ
        )
        return permission == Permission(None, redact_speaker_names=True, meeting_id=unit.meeting)

    # Act
    allowed = async_database.run(scenario)
    # Assert
    assert allowed


def test_declined_requester_cannot_read_through_the_share(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=False)
        return await refusal(
            unit.access.policy.authorize_share(share_id, unit.outsider, ContentPath.READ)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


@pytest.mark.parametrize(
    "path", [ContentPath.EXPORT, ContentPath.MCP, ContentPath.RECORDING, ContentPath.WRITE]
)
def test_share_recipient_may_only_read(async_database: AsyncDatabase, path: ContentPath) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        return await refusal(unit.access.policy.authorize_share(share_id, unit.outsider, path))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_revoked_share_stops_its_recipient_reading(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        await unit.access.revoke(unit.owner, share_id, NOW)
        return await refusal(
            unit.access.policy.authorize_share(share_id, unit.outsider, ContentPath.READ)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.SHARE_REVOKED


def test_only_the_share_creator_decides_requests(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        return await refusal(
            unit.access.decide(unit.member, request.share_access_request_id, NOW, approve=True)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_decided_request_cannot_be_decided_again(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        request_id = request.share_access_request_id
        await unit.access.decide(unit.owner, request_id, NOW, approve=False)
        return await refusal(unit.access.decide(unit.owner, request_id, NOW, approve=True))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.ACCESS_REQUEST_NOT_PENDING


def test_request_to_a_revoked_share_cannot_be_approved(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.revoke(unit.owner, share_id, NOW)
        return await refusal(
            unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.SHARE_REVOKED


def test_share_is_bound_to_one_recipient(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        second = (await AsyncDatabase.add_account(session, PASSWORD)).user_id
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        first = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        later = await unit.access.request_access(second, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, first.share_access_request_id, NOW, approve=True)
        return await refusal(
            unit.access.decide(unit.owner, later.share_access_request_id, NOW, approve=True)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.SHARE_ALREADY_BOUND


def test_bound_recipient_already_has_access(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        return await refusal(
            unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.ALREADY_HAS_ACCESS


def test_unknown_request_cannot_be_decided(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(unit.access.decide(unit.owner, uuid4(), NOW, approve=True))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


def test_revoking_twice_audits_once(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[AuditAction]:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        await unit.access.revoke(unit.owner, created.share.share_id, NOW)
        await unit.access.revoke(unit.owner, created.share.share_id, NOW + timedelta(hours=1))
        return [event.action for event in unit.audit.events]

    # Act
    actions = async_database.run(scenario)
    # Assert
    assert actions == [AuditAction.SHARE_CREATED, AuditAction.SHARE_REVOKED]


def test_unknown_share_cannot_be_revoked(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(unit.access.revoke(unit.owner, uuid4(), NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


# --- Listing shares and requests ---


def test_meeting_shares_list_newest_first(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        older = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        newer = await unit.access.create_share(
            unit.owner, unit.meeting, NOW + timedelta(minutes=1), redact=False
        )
        shares = await unit.access.shares(unit.member, unit.meeting)
        return [share.share_id for share in shares] == [
            newer.share.share_id,
            older.share.share_id,
        ]

    # Act
    ordered = async_database.run(scenario)
    # Assert
    assert ordered


def test_share_requests_are_listed_for_the_creator(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        requests = await unit.access.requests(unit.owner, share_id)
        return [found.share_access_request_id for found in requests] == [
            request.share_access_request_id
        ]

    # Act
    listed = async_database.run(scenario)
    # Assert
    assert listed


def test_requests_of_an_unknown_share_are_missing(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(unit.access.requests(unit.owner, uuid4()))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


# --- Requester profiles ---


def test_creator_sees_the_requesters_own_profile(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> UserProfile:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        request = await unit.access.request_access(
            unit.outsider, created.share.share_id, created.token, NOW
        )
        return await unit.access.requester_profile(unit.owner, request.share_access_request_id)

    # Act
    profile = async_database.run(scenario)
    # Assert
    assert profile == UserProfile("Oksana", "oksana@example.com")


def test_other_member_cannot_see_the_requester_profile(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        request = await unit.access.request_access(
            unit.outsider, created.share.share_id, created.token, NOW
        )
        return await refusal(
            unit.access.requester_profile(unit.member, request.share_access_request_id)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_profile_of_an_unknown_request_is_missing(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        return await refusal(unit.access.requester_profile(unit.owner, uuid4()))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


# --- Eviction notices ---


def test_eviction_tells_who_still_could_read_the_meeting(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        scope = await unit.meetings.scope(unit.meeting)
        found = await unit.access.policy.eviction_recipients(scope, unit.outsider)
        return found == {unit.owner: True, unit.outsider: False}

    # Act
    matches = async_database.run(scenario)
    # Assert
    assert matches


def test_eviction_counts_a_share_recipient_as_a_reader(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        request = await unit.access.request_access(
            unit.outsider, created.share.share_id, created.token, NOW
        )
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        scope = await unit.meetings.scope(unit.meeting)
        found = await unit.access.policy.eviction_recipients(scope, unit.outsider)
        return found[unit.outsider]

    # Act
    reader = async_database.run(scenario)
    # Assert
    assert reader
