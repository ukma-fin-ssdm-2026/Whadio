import asyncio
import hashlib
import math
import secrets
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from ..audit.services import (
    IAccountAuditWriter,
    IInvitationAuditWriter,
    InvitationCancelled,
    IWorkspaceAuditWriter,
    McpKeyCreated,
    McpKeyRevoked,
    MemberInvited,
    WorkspaceDeleted,
)
from ..shared.errors import Failure, RateLimitError, UseCaseError
from ..shared.pagination import ListWindow
from ..shared.text import display_text
from .contracts import UserProfile
from .enums import InvitationRole, NotesTemplate, RegistrationMode, SessionKind, WorkspaceRole
from .models import User
from .passwords import IPasswordHasher, is_password_strong
from .repositories import (
    IIdentityRepository,
    IInvitationRepository,
    IMcpKeyRepository,
    IMembershipRepository,
    InvitationIssue,
    IRegistrationRepository,
    ISessionRepository,
    IWorkspaceRepository,
    IWorkspaceSettingsRepository,
    McpKeyRevokeResult,
    MemberWorkspace,
    PersonalMcpKey,
    WorkspaceInvitation,
)

SESSION_LIFETIMES: Final = {
    SessionKind.BROWSER: timedelta(days=14),
    SessionKind.EXTENSION: timedelta(hours=24),
}


class IWorkspaceMembership(Protocol):
    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None: ...


class IWorkspaceDirectory(IWorkspaceMembership, Protocol):
    async def members(self, workspace_id: UUID) -> list[UUID]: ...

    async def profile(self, user_id: UUID) -> UserProfile | None: ...

    async def workspaces(self, user_id: UUID) -> list[UUID]: ...


class IWorkspaceCapacity(Protocol):
    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        """Lock the Owner across concurrent ingests, then return all their workspaces."""
        ...


class WorkspaceMembershipService:
    def __init__(self, repository: IMembershipRepository) -> None:
        self._repository: IMembershipRepository = repository

    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        return await self._repository.capacity_workspaces(workspace_id)

    async def role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.role(workspace_id, user_id)

    async def lock_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole | None:
        return await self._repository.lock_role(workspace_id, user_id)

    async def members(self, workspace_id: UUID) -> list[UUID]:
        return await self._repository.members(workspace_id)

    async def profile(self, user_id: UUID) -> UserProfile | None:
        return await self._repository.profile(user_id)

    async def workspaces(self, user_id: UUID) -> list[UUID]:
        return await self._repository.workspaces(user_id)


class IdentityService:
    def __init__(self, repository: IIdentityRepository) -> None:
        self._repository: IIdentityRepository = repository

    async def session_user(self, token: str, kind: SessionKind, now: datetime) -> User | None:
        return await self._repository.session_user(token, kind, now)

    async def mcp_user(self, token: str, now: datetime) -> User | None:
        return await self._repository.mcp_user(token, now)


class IWorkspaceSettings(Protocol):
    async def default_template(self, workspace_id: UUID, /) -> NotesTemplate: ...


class WorkspaceSettingsService:
    def __init__(self, repository: IWorkspaceSettingsRepository) -> None:
        self._repository: IWorkspaceSettingsRepository = repository

    async def default_template(self, workspace_id: UUID) -> NotesTemplate:
        return await self._repository.default_template(workspace_id) or NotesTemplate.SUMMARY


# --- Signing in ---


@dataclass(frozen=True, slots=True)
class SignedIn:
    token: str
    expires_at: datetime
    user: User


class SignInService:
    def __init__(self, sessions: ISessionRepository, passwords: IPasswordHasher) -> None:
        self._sessions: ISessionRepository = sessions
        self._passwords: IPasswordHasher = passwords

    async def sign_in(
        self, email: str, password: str, kind: SessionKind, now: datetime
    ) -> SignedIn:
        user = await self._sessions.by_email(email)
        # Argon2 takes tens of milliseconds of CPU, so it runs off the event loop.
        if user is None:
            # Costs what a wrong password costs, so the timing does not tell which was wrong.
            await asyncio.to_thread(self._passwords.hash, password)
            raise UseCaseError(Failure.INVALID_CREDENTIALS)
        if not await asyncio.to_thread(self._passwords.verify, user.password_hash, password):
            raise UseCaseError(Failure.INVALID_CREDENTIALS)
        await self._sessions.end_expired_sessions(user.user_id, now)
        token = secrets.token_urlsafe(32)
        expires_at = now + SESSION_LIFETIMES[kind]
        await self._sessions.add_session(user.user_id, kind, token, expires_at, now)
        return SignedIn(token, expires_at, user)

    async def sign_out(self, tokens: Collection[str]) -> None:
        await self._sessions.end_sessions(tokens)


# --- MCP keys ---


@dataclass(frozen=True, slots=True)
class CreatedMcpKey:
    key: PersonalMcpKey
    secret: str


class McpKeyService:
    def __init__(self, keys: IMcpKeyRepository, audit: IAccountAuditWriter) -> None:
        self._keys: IMcpKeyRepository = keys
        self._audit: IAccountAuditWriter = audit

    async def list(self, user_id: UUID, page: ListWindow | None = None) -> list[PersonalMcpKey]:
        return await self._keys.of_user(user_id, page)

    async def create(
        self, user_id: UUID, expires_in_days: int | None, now: datetime
    ) -> CreatedMcpKey:
        secret = f"whadio_mcp_{secrets.token_urlsafe(32)}"
        expires_at = None if expires_in_days is None else now + timedelta(days=expires_in_days)
        key = await self._keys.add(
            user_id,
            hashlib.sha256(secret.encode()).hexdigest(),
            expires_at,
            now,
        )
        await self._audit.write(McpKeyCreated(user_id, key.key_id, now))
        return CreatedMcpKey(key, secret)

    async def revoke(self, user_id: UUID, key_id: UUID, now: datetime) -> None:
        result = await self._keys.revoke(user_id, key_id, now)
        if result is McpKeyRevokeResult.NOT_FOUND:
            raise UseCaseError(Failure.NOT_FOUND)
        if result is McpKeyRevokeResult.REVOKED:
            await self._audit.write(McpKeyRevoked(user_id, key_id, now))


# --- Workspaces ---


class IWorkspaceContent(Protocol):
    """What a workspace holds in modules above Accounts; Meetings implements it."""

    async def add_default_folder(self, workspace_id: UUID, now: datetime, /) -> None: ...

    async def remove_meetings(self, workspace_id: UUID, now: datetime, /) -> None: ...


class WorkspaceService:
    def __init__(
        self,
        workspaces: IWorkspaceRepository,
        memberships: IWorkspaceMembership,
        content: IWorkspaceContent,
        audit: IWorkspaceAuditWriter,
    ) -> None:
        self._workspaces: IWorkspaceRepository = workspaces
        self._memberships: IWorkspaceMembership = memberships
        self._content: IWorkspaceContent = content
        self._audit: IWorkspaceAuditWriter = audit

    async def list_workspaces(self, user_id: UUID) -> list[MemberWorkspace]:
        return await self._workspaces.of_member(user_id, None)

    async def get(self, user_id: UUID, workspace_id: UUID) -> MemberWorkspace:
        found = await self._workspaces.of_member(user_id, workspace_id)
        if not found:
            raise UseCaseError(Failure.NOT_FOUND)
        return found[0]

    async def create(
        self, user_id: UUID, name: str, template: NotesTemplate, now: datetime
    ) -> MemberWorkspace:
        workspace_id = await self._workspaces.add(name, template, user_id, now)
        await self._content.add_default_folder(workspace_id, now)
        return await self.get(user_id, workspace_id)

    async def update(
        self, user_id: UUID, workspace_id: UUID, name: str | None, template: NotesTemplate | None
    ) -> MemberWorkspace:
        await self._owned(user_id, workspace_id)
        await self._workspaces.update(workspace_id, name, template)
        return await self.get(user_id, workspace_id)

    async def delete(self, user_id: UUID, workspace_id: UUID, now: datetime) -> None:
        """Queues the workspace's recordings for deletion from storage once this commits."""
        if (await self._owned(user_id, workspace_id)).is_personal:
            raise UseCaseError(Failure.PERSONAL_WORKSPACE)
        await self._content.remove_meetings(workspace_id, now)
        await self._audit.write(WorkspaceDeleted(user_id, workspace_id, now))
        await self._workspaces.remove(workspace_id)

    async def _owned(self, user_id: UUID, workspace_id: UUID) -> MemberWorkspace:
        # Locked, the role cannot change between this check and the change it allows.
        role = await self._memberships.lock_role(workspace_id, user_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role is not WorkspaceRole.OWNER:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        return await self.get(user_id, workspace_id)


# --- Invitations ---


INVITATION_LIFETIME: Final = timedelta(days=7)
INVITATION_WINDOW: Final = timedelta(days=1)
INVITATION_DAILY_LIMIT: Final = 20


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: WorkspaceInvitation
    token: str = field(repr=False)
    replaced: bool

    def url(self, public_url: str) -> str:
        return (
            f"{public_url.rstrip('/')}/invitations/{self.invitation.invitation_id}"
            f"#token={self.token}"
        )


@dataclass(frozen=True, slots=True)
class InvitationRequest:
    email: str
    role: InvitationRole
    mode: RegistrationMode


class InvitationService:
    def __init__(
        self,
        invitations: IInvitationRepository,
        memberships: IWorkspaceMembership,
        audit: IInvitationAuditWriter,
    ) -> None:
        self._invitations: IInvitationRepository = invitations
        self._memberships: IWorkspaceMembership = memberships
        self._audit: IInvitationAuditWriter = audit

    async def invite(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        request: InvitationRequest,
        now: datetime,
    ) -> IssuedInvitation:
        await self._invitations.lock_inviter(actor_id)
        actor_role = await self._moderator(actor_id, workspace_id, lock=True)
        normalized_email = request.email.lower()
        if await self._invitations.workspace_is_personal(workspace_id):
            raise UseCaseError(Failure.PERSONAL_WORKSPACE)
        if await self._invitations.email_is_member(workspace_id, normalized_email):
            raise UseCaseError(Failure.ALREADY_MEMBER)
        since = now - INVITATION_WINDOW
        window = await self._invitations.inviter_window(actor_id, since)
        if window.count >= INVITATION_DAILY_LIMIT:
            raise RateLimitError(
                Failure.INVITATION_LIMIT,
                self._retry_after(window.earliest_created_at, now),
            )
        if request.mode is RegistrationMode.VERIFIED:
            latest = await self._invitations.latest_created_at(workspace_id, normalized_email)
            if latest is not None and latest > since:
                raise RateLimitError(Failure.INVITATION_COOLDOWN, self._retry_after(latest, now))
            # Accountless email delivery is supplied by #188. Refuse instead of creating a link
            # that the API would neither return nor send.
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        token = secrets.token_urlsafe(32)
        invitation, replaced = await self._invitations.issue(
            InvitationIssue(
                workspace_id,
                normalized_email,
                request.role,
                actor_id,
                hashlib.sha256(token.encode()).hexdigest(),
                now,
                now + INVITATION_LIFETIME,
                actor_role,
            )
        )
        await self._audit.write(
            MemberInvited(actor_id, workspace_id, invitation.invitation_id, request.role.value, now)
        )
        return IssuedInvitation(invitation, token, replaced)

    async def list_pending(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        page: ListWindow,
    ) -> list[WorkspaceInvitation]:
        await self._moderator(actor_id, workspace_id, lock=False)
        return await self._invitations.pending(workspace_id, page)

    async def cancel(
        self, actor_id: UUID, workspace_id: UUID, invitation_id: UUID, now: datetime
    ) -> WorkspaceInvitation:
        await self._moderator(actor_id, workspace_id, lock=True)
        result = await self._invitations.cancel(workspace_id, invitation_id, now)
        if result is None:
            raise UseCaseError(Failure.NOT_FOUND)
        invitation, was_pending = result
        if not was_pending:
            raise UseCaseError(Failure.INVITATION_NOT_PENDING)
        await self._audit.write(InvitationCancelled(actor_id, workspace_id, invitation_id, now))
        return invitation

    async def _moderator(self, actor_id: UUID, workspace_id: UUID, *, lock: bool) -> WorkspaceRole:
        role = (
            await self._memberships.lock_role(workspace_id, actor_id)
            if lock
            else await self._memberships.role(workspace_id, actor_id)
        )
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role is WorkspaceRole.MEMBER:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        return role

    @staticmethod
    def _retry_after(created_at: datetime | None, now: datetime) -> int:
        if created_at is None:
            return math.ceil(INVITATION_WINDOW.total_seconds())
        return max(1, math.ceil((created_at + INVITATION_WINDOW - now).total_seconds()))


# --- Registration ---


REGISTRATION_LIFETIME: Final = timedelta(hours=24)


class AccountAlreadyExistsError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RegistrationDetails:
    name: str
    password: str = field(repr=False)
    accept_terms: bool


class RegistrationValidationError(Exception):
    def __init__(self, field_name: str, message: str) -> None:
        self.field_name: str = field_name
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RegistrationLink:
    registration_id: UUID
    token: str = field(repr=False)

    def url(self, public_url: str) -> str:
        return f"{public_url.rstrip('/')}/registrations/{self.registration_id}#token={self.token}"


class RegistrationIssuer:
    def __init__(
        self, registrations: IRegistrationRepository, sessions: ISessionRepository
    ) -> None:
        self._registrations: IRegistrationRepository = registrations
        self._sessions: ISessionRepository = sessions

    async def issue(self, email: str, now: datetime) -> RegistrationLink:
        await self._registrations.lock_email(email)
        if await self._sessions.by_email(email) is not None:
            raise AccountAlreadyExistsError
        token = secrets.token_urlsafe(32)
        registration_id = await self._registrations.issue(
            email, hashlib.sha256(token.encode()).hexdigest(), now, now + REGISTRATION_LIFETIME
        )
        return RegistrationLink(registration_id, token)


class RegistrationService:
    def __init__(
        self,
        registrations: IRegistrationRepository,
        sessions: ISessionRepository,
        passwords: IPasswordHasher,
        content: IWorkspaceContent,
        workspaces: IWorkspaceRepository,
    ) -> None:
        self._registrations: IRegistrationRepository = registrations
        self._sessions: ISessionRepository = sessions
        self._passwords: IPasswordHasher = passwords
        self._content: IWorkspaceContent = content
        self._workspaces: IWorkspaceRepository = workspaces

    async def complete(
        self,
        registration_id: UUID,
        token: str,
        details: RegistrationDetails,
        now: datetime,
    ) -> SignedIn:
        pending = await self._registrations.pending(registration_id)
        if pending is None:
            raise UseCaseError(Failure.LINK_INVALID)
        await self._registrations.lock_email(pending.email)
        # Re-read after locking: another request may have used or replaced the link while we waited.
        pending = await self._registrations.pending(registration_id)
        if (
            pending is None
            or pending.expires_at <= now
            or not secrets.compare_digest(
                pending.token_hash, hashlib.sha256(token.encode()).hexdigest()
            )
            or await self._sessions.by_email(pending.email) is not None
        ):
            raise UseCaseError(Failure.LINK_INVALID)
        if not is_password_strong(details.password):
            raise RegistrationValidationError(
                "password", "Use 12 to 128 characters, at least one digit and one uppercase letter"
            )
        if not details.accept_terms:
            raise RegistrationValidationError("accept_terms", "Accept the Terms and Conditions")
        try:
            name = display_text(details.name)
        except ValueError as error:
            raise RegistrationValidationError("name", str(error)) from None
        password_hash = await asyncio.to_thread(self._passwords.hash, details.password)
        user = await self._registrations.create_account(pending.email, name, password_hash, now)
        workspace_id = await self._workspaces.add(
            name, NotesTemplate.DETAILED, user.user_id, now, personal=True
        )
        await self._content.add_default_folder(workspace_id, now)
        session_token = secrets.token_urlsafe(32)
        expires_at = now + SESSION_LIFETIMES[SessionKind.BROWSER]
        await self._sessions.add_session(
            user.user_id, SessionKind.BROWSER, session_token, expires_at, now
        )
        return SignedIn(session_token, expires_at, user)


class RegistrationCleanupService:
    def __init__(self, registrations: IRegistrationRepository) -> None:
        self._registrations: IRegistrationRepository = registrations

    async def remove_expired(self, now: datetime) -> int:
        return await self._registrations.delete_expired(now)
