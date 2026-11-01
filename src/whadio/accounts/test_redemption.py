import asyncio
from collections.abc import Awaitable, Collection
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ..audit.services import MemberJoined
from ..shared.errors import Failure, UseCaseError
from .enums import InvitationRole, InvitationStatus, SessionKind, WorkspaceRole
from .models import Invitation, PendingRegistration, User, WorkspaceMembership
from .redemption import RedemptionService
from .redemption_repository import InvitationLink
from .services import RegistrationDetails, SignedIn
from .tokens import generated_token_hash

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
TOKEN = uuid4().hex
DETAILS = RegistrationDetails("Alice", "StrongPassword123", accept_terms=True)


class Repository:
    def __init__(self, calls: list[str]) -> None:
        self.calls: list[str] = calls
        self.invitation: Invitation | None = Invitation(
            invitation_id=uuid4(),
            workspace_id=uuid4(),
            invited_email="alice@example.com",
            invited_by_user_id=uuid4(),
            role=InvitationRole.MEMBER,
            status=InvitationStatus.PENDING,
            token_hash=generated_token_hash(TOKEN),
            created_at=NOW,
            expires_at=NOW + timedelta(days=7),
            responded_at=None,
        )
        self.creator_role: WorkspaceRole | None = WorkspaceRole.OWNER
        self.member: WorkspaceMembership | None = None
        self.locked_status: InvitationStatus | None = None
        self.locked_token: str | None = None
        self.lose_authority: bool = False
        self.disappear: bool = False

    async def find(self, invitation_id: UUID) -> InvitationLink | None:
        del invitation_id
        self.calls.append("read")
        return None if self.invitation is None else InvitationLink(self.invitation, "Team")

    async def lock(self, invitation_id: UUID) -> Invitation | None:
        del invitation_id
        self.calls.append("workspace-lock")
        if self.lose_authority:
            self.creator_role = WorkspaceRole.MEMBER
        if self.disappear:
            return None
        if self.invitation is not None:
            if self.locked_status is not None:
                self.invitation.status = self.locked_status
            if self.locked_token is not None:
                self.invitation.token_hash = generated_token_hash(self.locked_token)
        return self.invitation

    async def account_exists(self, email: str) -> bool:
        del email
        self.calls.append("account-exists")
        return False

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership | None:
        del workspace_id
        if self.invitation is not None and user_id == self.invitation.invited_by_user_id:
            self.calls.append("creator")
            return (
                None if self.creator_role is None else WorkspaceMembership(role=self.creator_role)
            )
        self.calls.append("membership")
        return self.member

    async def join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership:
        self.calls.append("join")
        self.member = WorkspaceMembership(
            workspace_id=invitation.workspace_id,
            user_id=user_id,
            role=WorkspaceRole.MEMBER,
            joined_at=now,
        )
        await self.answer(invitation, InvitationStatus.ACCEPTED, now)
        return self.member

    async def answer(self, invitation: Invitation, status: InvitationStatus, now: datetime) -> None:
        self.calls.append("answer")
        invitation.status, invitation.responded_at = status, now


class Accounts:
    def __init__(self, calls: list[str]) -> None:
        self.calls: list[str] = calls
        self.user: User | None = None

    async def lock_email(self, email: str) -> None:
        del email
        self.calls.append("email-lock")

    async def by_email(self, email: str) -> User | None:
        del email
        self.calls.append("account")
        return self.user

    async def pending(self, registration_id: UUID) -> PendingRegistration | None:
        del registration_id
        raise NotImplementedError

    async def issue(self, email: str, token_hash: str, now: datetime, expires_at: datetime) -> UUID:
        del email, token_hash, now, expires_at
        raise NotImplementedError

    async def create_account(
        self, email: str, name: str, password_hash: str, now: datetime
    ) -> User:
        del email, name, password_hash, now
        raise NotImplementedError

    async def delete_expired(self, now: datetime) -> int:
        del now
        raise NotImplementedError

    async def account_for_update(self, email: str) -> User | None:
        del email
        raise NotImplementedError

    async def lock_account(self, user_id: UUID) -> None:
        del user_id
        raise NotImplementedError

    async def add_session(
        self,
        user_id: UUID,
        kind: SessionKind,
        token: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        del user_id, kind, token, expires_at, now
        raise NotImplementedError

    async def end_sessions(self, tokens: Collection[str]) -> None:
        del tokens
        raise NotImplementedError

    async def end_expired_sessions(self, user_id: UUID, now: datetime) -> None:
        del user_id, now
        raise NotImplementedError

    async def provision(self, email: str, details: RegistrationDetails, now: datetime) -> SignedIn:
        self.calls.append("provision")
        return SignedIn(
            "session",
            now + timedelta(days=14),
            User(user_id=uuid4(), email=email, name=details.name),
        )


class Audit:
    def __init__(self, calls: list[str]) -> None:
        self.calls: list[str] = calls
        self.events: list[MemberJoined] = []

    async def write(self, event: MemberJoined) -> None:
        self.calls.append("audit")
        self.events.append(event)


class World:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.repository: Repository = Repository(self.calls)
        self.accounts: Accounts = Accounts(self.calls)
        self.audit: Audit = Audit(self.calls)
        self.service: RedemptionService = RedemptionService(
            self.repository, self.accounts, self.accounts, self.accounts, self.audit
        )
        self.user_id: UUID = uuid4()

    async def redeem(self, operation: str, token: str = TOKEN) -> None:
        invitation = self.repository.invitation
        invitation_id = uuid4() if invitation is None else invitation.invitation_id
        if operation == "preview":
            await self.service.preview(invitation_id, token, NOW)
        elif operation == "decline":
            await self.service.decline(invitation_id, token, NOW)
        elif operation == "accept":
            await self.service.accept(invitation_id, token, self.user_id, "ALICE@example.com", NOW)
        else:
            await self.service.register(invitation_id, token, DETAILS, NOW)


async def refusal[T](operation: Awaitable[T]) -> Failure | None:
    try:
        await operation
    except UseCaseError as error:
        return error.code
    return None


@pytest.mark.parametrize("operation", ["preview", "accept", "decline", "register"])
@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "surrogate",
        "token",
        "expired",
        "cancelled",
        "declined",
        "accepted",
        "removed",
        "demoted",
    ],
)
def test_link_checks_precede_locks_and_account_disclosure(operation: str, invalid: str) -> None:
    # Arrange
    world = World()
    invitation = world.repository.invitation
    assert invitation is not None
    token = TOKEN
    if invalid == "missing":
        world.repository.invitation = None
    elif invalid == "surrogate":
        token = chr(0xD800)
    elif invalid == "token":
        token = uuid4().hex
    elif invalid == "expired":
        invitation.expires_at = NOW
    elif invalid in ("cancelled", "declined", "accepted"):
        invitation.status = InvitationStatus(invalid)
    else:
        world.repository.creator_role = None if invalid == "removed" else WorkspaceRole.MEMBER
    if invalid == "accepted" and operation == "accept":
        world.repository.creator_role = None
    # Act
    failure = asyncio.run(refusal(world.redeem(operation, token)))
    # Assert
    authority_checked = invalid in ("removed", "demoted") or (
        invalid == "accepted" and operation == "accept"
    )
    assert (failure, world.calls) == (
        Failure.LINK_INVALID,
        ["read", "creator"] if authority_checked else ["read"],
    )


def test_preview_only_reads_link_authority_and_account_existence() -> None:
    # Arrange
    world = World()
    # Act
    asyncio.run(world.redeem("preview"))
    # Assert
    assert world.calls == ["read", "creator", "account-exists"]


def test_register_locks_email_before_workspace_and_rechecks_link_before_provisioning() -> None:
    # Arrange
    world = World()
    # Act
    asyncio.run(world.redeem("register"))
    # Assert
    assert world.calls == [
        "read",
        "creator",
        "email-lock",
        "workspace-lock",
        "creator",
        "account",
        "provision",
        "join",
        "answer",
        "audit",
    ]


@pytest.mark.parametrize("operation", ["accept", "decline", "register"])
@pytest.mark.parametrize("change", ["status", "token", "deleted", "authority"])
def test_writes_revalidate_link_after_locking(operation: str, change: str) -> None:
    # Arrange
    world = World()
    world.repository.locked_status = InvitationStatus.CANCELLED if change == "status" else None
    world.repository.locked_token = "replacement" if change == "token" else None
    world.repository.disappear = change == "deleted"
    world.repository.lose_authority = change == "authority"
    # Act
    failure = asyncio.run(refusal(world.redeem(operation)))
    # Assert
    assert (failure, set(world.calls) & {"provision", "join", "answer", "audit"}) == (
        Failure.LINK_INVALID,
        set(),
    )


def test_register_refuses_existing_account_before_provisioning() -> None:
    # Arrange
    world = World()
    world.accounts.user = User(user_id=world.user_id)
    # Act
    failure = asyncio.run(refusal(world.redeem("register")))
    # Assert
    assert (failure, world.calls[-1]) == (Failure.ACCOUNT_EXISTS, "account")


def test_accept_refuses_existing_membership_without_joining() -> None:
    # Arrange
    world = World()
    world.repository.member = WorkspaceMembership(user_id=world.user_id, joined_at=NOW)
    # Act
    failure = asyncio.run(refusal(world.redeem("accept")))
    # Assert
    assert (failure, world.audit.events) == (Failure.ALREADY_MEMBER, [])


def test_repeated_acceptance_audits_once() -> None:
    # Arrange
    world = World()

    # Act
    async def scenario() -> list[MemberJoined]:
        await world.redeem("accept")
        await world.redeem("accept")
        return world.audit.events

    events = asyncio.run(scenario())
    # Assert
    assert len(events) == 1


@pytest.mark.parametrize("status", [InvitationStatus.PENDING, InvitationStatus.ACCEPTED])
def test_email_mismatch_is_disclosed_only_for_pending_links(status: InvitationStatus) -> None:
    # Arrange
    world = World()
    invitation = world.repository.invitation
    assert invitation is not None
    invitation.status = status
    # Act
    failure = asyncio.run(
        refusal(
            world.service.accept(
                invitation.invitation_id, TOKEN, world.user_id, "other@example.com", NOW
            )
        )
    )
    # Assert
    assert failure is (
        Failure.EMAIL_MISMATCH if status is InvitationStatus.PENDING else Failure.LINK_INVALID
    )


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.MODERATOR])
def test_current_owner_or_moderator_authorizes_redemption(role: WorkspaceRole) -> None:
    # Arrange
    world = World()
    world.repository.creator_role = role
    # Act
    failure = asyncio.run(refusal(world.redeem("decline")))
    # Assert
    assert failure is None


@pytest.mark.parametrize("replaced", [False, True])
def test_accept_retry_refuses_missing_or_replaced_membership(*, replaced: bool) -> None:
    # Arrange
    world = World()
    invitation = world.repository.invitation
    assert invitation is not None
    invitation.status, invitation.responded_at = InvitationStatus.ACCEPTED, NOW
    if replaced:
        world.repository.member = WorkspaceMembership(
            user_id=world.user_id, joined_at=NOW + timedelta(seconds=1)
        )
    # Act
    failure = asyncio.run(refusal(world.redeem("accept")))
    # Assert
    assert failure is Failure.LINK_INVALID
