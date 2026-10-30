import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ..audit.services import InvitationCancelled, MemberInvited
from ..shared.errors import Failure, RateLimitError, UseCaseError
from ..shared.pagination import ListWindow
from .enums import InvitationRole, InvitationStatus, RegistrationMode, WorkspaceRole
from .repositories import InvitationIssue, InvitationWindow, WorkspaceInvitation
from .services import INVITATION_LIFETIME, InvitationRequest, InvitationService

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


class Invitations:
    def __init__(self) -> None:
        self.personal: bool = False
        self.member: bool = False
        self.window: InvitationWindow = InvitationWindow(0, None)
        self.latest: datetime | None = None
        self.issued_hash: str | None = None
        self.issued_email: str | None = None
        self.invitation: WorkspaceInvitation = WorkspaceInvitation(
            uuid4(),
            uuid4(),
            "new@example.com",
            InvitationRole.MEMBER,
            InvitationStatus.PENDING,
            uuid4(),
            NOW,
            NOW + INVITATION_LIFETIME,
            None,
            WorkspaceRole.OWNER,
        )
        self.cancelled_pending: bool = True

    async def lock_inviter(self, user_id: UUID) -> None:
        del user_id

    async def workspace_is_personal(self, workspace_id: UUID) -> bool:
        del workspace_id
        return self.personal

    async def email_is_member(self, workspace_id: UUID, email: str) -> bool:
        del workspace_id, email
        return self.member

    async def inviter_window(self, inviter_id: UUID, since: datetime) -> InvitationWindow:
        del inviter_id, since
        return self.window

    async def latest_created_at(self, workspace_id: UUID, email: str) -> datetime | None:
        del workspace_id, email
        return self.latest

    async def issue(self, issue: InvitationIssue) -> tuple[WorkspaceInvitation, bool]:
        self.issued_hash = issue.token_hash
        self.issued_email = issue.email
        self.invitation = WorkspaceInvitation(
            self.invitation.invitation_id,
            issue.workspace_id,
            issue.email,
            issue.role,
            InvitationStatus.PENDING,
            issue.inviter_id,
            issue.now,
            issue.expires_at,
            None,
            issue.inviter_role,
        )
        return self.invitation, False

    async def pending(self, workspace_id: UUID, page: ListWindow) -> list[WorkspaceInvitation]:
        del workspace_id, page
        return [self.invitation]

    async def cancel(
        self, workspace_id: UUID, invitation_id: UUID, now: datetime
    ) -> tuple[WorkspaceInvitation, bool] | None:
        del workspace_id, invitation_id
        cancelled = WorkspaceInvitation(
            self.invitation.invitation_id,
            self.invitation.workspace_id,
            self.invitation.invited_email,
            self.invitation.role,
            InvitationStatus.CANCELLED,
            self.invitation.invited_by_user_id,
            self.invitation.created_at,
            self.invitation.expires_at,
            now,
            self.invitation.inviter_role,
        )
        return cancelled, self.cancelled_pending


class Memberships:
    def __init__(self, role: WorkspaceRole | None = WorkspaceRole.OWNER) -> None:
        self.role_value: WorkspaceRole | None = role

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        del workspace_id, user_id
        return self.role_value


class Audit:
    def __init__(self) -> None:
        self.events: list[MemberInvited | InvitationCancelled] = []

    async def write(self, event: MemberInvited | InvitationCancelled) -> None:
        self.events.append(event)


def test_invitation_secret_is_stored_only_as_a_hash() -> None:
    # Arrange
    invitations, audit = Invitations(), Audit()
    actor_id, workspace_id = uuid4(), uuid4()

    async def scenario() -> tuple[
        str,
        str | None,
        str | None,
        list[MemberInvited | InvitationCancelled],
    ]:
        issued = await InvitationService(invitations, Memberships(), audit).invite(
            actor_id,
            workspace_id,
            InvitationRequest(
                "New@Example.COM", InvitationRole.MODERATOR, RegistrationMode.INVITE_ONLY
            ),
            NOW,
        )
        return issued.token, invitations.issued_hash, invitations.issued_email, audit.events

    # Act
    token, stored_hash, email, events = asyncio.run(scenario())
    # Assert
    assert (
        stored_hash == hashlib.sha256(token.encode()).hexdigest(),
        stored_hash != token,
        email,
        events,
    ) == (
        True,
        True,
        "new@example.com",
        [
            MemberInvited(
                actor_id,
                workspace_id,
                invitations.invitation.invitation_id,
                "Moderator",
                NOW,
            )
        ],
    )


def test_verified_mode_cooldown_has_retry_after_and_does_not_issue() -> None:
    # Arrange
    invitations = Invitations()
    invitations.latest = NOW - timedelta(hours=2)

    async def scenario() -> None:
        await InvitationService(invitations, Memberships(), Audit()).invite(
            uuid4(),
            uuid4(),
            InvitationRequest("new@example.com", InvitationRole.MEMBER, RegistrationMode.VERIFIED),
            NOW,
        )

    # Act
    with pytest.raises(RateLimitError) as failure:
        asyncio.run(scenario())
    # Assert
    assert (failure.value.code, failure.value.retry_after, invitations.issued_hash) == (
        Failure.INVITATION_COOLDOWN,
        22 * 60 * 60,
        None,
    )


def test_member_cannot_list_invitations() -> None:
    # Arrange
    async def scenario() -> None:
        await InvitationService(
            Invitations(), Memberships(WorkspaceRole.MEMBER), Audit()
        ).list_pending(uuid4(), uuid4(), ListWindow(21, None))

    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(scenario())
    # Assert
    assert failure.value.code is Failure.INSUFFICIENT_ROLE


def test_repeated_cancellation_is_rejected_without_audit() -> None:
    # Arrange
    invitations, audit = Invitations(), Audit()
    invitations.cancelled_pending = False

    async def scenario() -> None:
        await InvitationService(invitations, Memberships(), audit).cancel(
            uuid4(), uuid4(), invitations.invitation.invitation_id, NOW
        )

    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(scenario())
    # Assert
    assert (failure.value.code, audit.events) == (Failure.INVITATION_NOT_PENDING, [])


def test_link_is_inactive_when_inviter_loses_authority() -> None:
    # Arrange
    invitation = Invitations().invitation
    demoted = WorkspaceInvitation(
        invitation.invitation_id,
        invitation.workspace_id,
        invitation.invited_email,
        invitation.role,
        invitation.status,
        invitation.invited_by_user_id,
        invitation.created_at,
        invitation.expires_at,
        invitation.responded_at,
        WorkspaceRole.MEMBER,
    )
    # Act
    active = demoted.link_active(NOW)
    # Assert
    assert not active
