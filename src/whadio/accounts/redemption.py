import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.services import IMemberJoinAuditWriter, MemberJoined
from ..shared.errors import Failure, UseCaseError
from .enums import InvitationStatus, WorkspaceRole
from .models import Invitation, Workspace, WorkspaceMembership
from .repositories import IRegistrationRepository, ISessionRepository
from .services import RegistrationDetails, RegistrationService, SignedIn


class IRedemptionRepository(Protocol):
    async def find(self, invitation_id: UUID) -> Invitation | None: ...

    async def lock(self, invitation_id: UUID) -> Invitation | None: ...

    async def workspace_name(self, workspace_id: UUID) -> str: ...

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership | None: ...

    async def join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership: ...

    async def answer(
        self, invitation: Invitation, status: InvitationStatus, now: datetime
    ) -> None: ...


class RedemptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def find(self, invitation_id: UUID) -> Invitation | None:
        return await self._session.scalar(
            select(Invitation)
            .where(Invitation.invitation_id == invitation_id)
            .execution_options(populate_existing=True)
        )

    async def lock(self, invitation_id: UUID) -> Invitation | None:
        invitation = await self.find(invitation_id)
        if invitation is None:
            return None
        # Match management's workspace-before-invitation order, including role changes in #184.
        await self._session.scalar(
            select(Workspace.workspace_id)
            .where(Workspace.workspace_id == invitation.workspace_id)
            .with_for_update()
        )
        return await self._session.scalar(
            select(Invitation)
            .where(Invitation.invitation_id == invitation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def workspace_name(self, workspace_id: UUID) -> str:
        name = await self._session.scalar(
            select(Workspace.name).where(Workspace.workspace_id == workspace_id)
        )
        if name is None:
            raise UseCaseError(Failure.LINK_INVALID)
        return name

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership | None:
        return await self._session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    async def join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership:
        member = WorkspaceMembership(
            workspace_id=invitation.workspace_id,
            user_id=user_id,
            role=WorkspaceRole(invitation.role.value),
            joined_at=now,
        )
        self._session.add(member)
        await self.answer(invitation, InvitationStatus.ACCEPTED, now)
        return member

    async def answer(self, invitation: Invitation, status: InvitationStatus, now: datetime) -> None:
        invitation.status = status
        invitation.responded_at = now
        await self._session.flush()


@dataclass(frozen=True)
class InvitationPreview:
    invitation: Invitation
    workspace_name: str
    account_exists: bool


class RedemptionService:
    def __init__(
        self,
        repository: IRedemptionRepository,
        registrations: IRegistrationRepository,
        sessions: ISessionRepository,
        provisioner: RegistrationService,
        audit: IMemberJoinAuditWriter,
    ) -> None:
        self._repository: IRedemptionRepository = repository
        self._registrations: IRegistrationRepository = registrations
        self._sessions: ISessionRepository = sessions
        self._provisioner: RegistrationService = provisioner
        self._audit: IMemberJoinAuditWriter = audit

    async def _valid(
        self, invitation_id: UUID, token: str, now: datetime, *, accepted: bool = False
    ) -> Invitation:
        invitation = await self._repository.lock(invitation_id)
        if (
            invitation is None
            or invitation.expires_at <= now
            or not secrets.compare_digest(
                invitation.token_hash, hashlib.sha256(token.encode()).hexdigest()
            )
            or invitation.status
            not in (
                (InvitationStatus.PENDING, InvitationStatus.ACCEPTED)
                if accepted
                else (InvitationStatus.PENDING,)
            )
        ):
            raise UseCaseError(Failure.LINK_INVALID)
        creator = await self._repository.membership(
            invitation.workspace_id, invitation.invited_by_user_id
        )
        if creator is None or creator.role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.LINK_INVALID)
        return invitation

    async def preview(self, invitation_id: UUID, token: str, now: datetime) -> InvitationPreview:
        invitation = await self._valid(invitation_id, token, now)
        return InvitationPreview(
            invitation,
            await self._repository.workspace_name(invitation.workspace_id),
            await self._sessions.by_email(invitation.invited_email) is not None,
        )

    async def accept(
        self, invitation_id: UUID, token: str, user_id: UUID, email: str, now: datetime
    ) -> WorkspaceMembership:
        invitation = await self._valid(invitation_id, token, now, accepted=True)
        if email.lower() != invitation.invited_email.lower():
            raise UseCaseError(Failure.EMAIL_MISMATCH)
        member = await self._repository.membership(invitation.workspace_id, user_id)
        if invitation.status is InvitationStatus.ACCEPTED:
            if member is None or member.joined_at != invitation.responded_at:
                raise UseCaseError(Failure.LINK_INVALID)
            return member
        if member is not None:
            raise UseCaseError(Failure.ALREADY_MEMBER)
        return await self._join(invitation, user_id, now)

    async def _join(
        self, invitation: Invitation, user_id: UUID, now: datetime
    ) -> WorkspaceMembership:
        member = await self._repository.join(invitation, user_id, now)
        await self._audit.write(
            MemberJoined(user_id, invitation.workspace_id, user_id, invitation.role.value, now)
        )
        return member

    async def decline(self, invitation_id: UUID, token: str, now: datetime) -> Invitation:
        invitation = await self._valid(invitation_id, token, now)
        await self._repository.answer(invitation, InvitationStatus.DECLINED, now)
        return invitation

    async def register(
        self, invitation_id: UUID, token: str, details: RegistrationDetails, now: datetime
    ) -> tuple[SignedIn, WorkspaceMembership]:
        candidate = await self._repository.find(invitation_id)
        if candidate is None:
            raise UseCaseError(Failure.LINK_INVALID)
        # Share registration's email lock before taking any workspace locks.
        await self._registrations.lock_email(candidate.invited_email)
        invitation = await self._valid(invitation_id, token, now)
        if await self._sessions.by_email(invitation.invited_email) is not None:
            raise UseCaseError(Failure.ACCOUNT_EXISTS)
        signed = await self._provisioner.provision(invitation.invited_email, details, now)
        member = await self._join(invitation, signed.user.user_id, now)
        return signed, member
