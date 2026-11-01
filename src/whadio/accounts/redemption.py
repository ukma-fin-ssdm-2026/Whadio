import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..audit.services import IMemberJoinAuditWriter, MemberJoined
from ..shared.errors import Failure, UseCaseError
from .enums import InvitationStatus, WorkspaceRole
from .models import Invitation, WorkspaceMembership
from .redemption_repository import InvitationLink, IRedemptionRepository
from .repositories import IRegistrationRepository, ISessionRepository
from .services import RegistrationDetails, SignedIn
from .tokens import supplied_token_hash


@dataclass(frozen=True)
class InvitationPreview:
    invitation: Invitation
    workspace_name: str
    account_exists: bool


class IAccountProvisioner(Protocol):
    async def provision(
        self, email: str, details: RegistrationDetails, now: datetime
    ) -> SignedIn: ...


class RedemptionService:
    def __init__(
        self,
        repository: IRedemptionRepository,
        registrations: IRegistrationRepository,
        sessions: ISessionRepository,
        provisioner: IAccountProvisioner,
        audit: IMemberJoinAuditWriter,
    ) -> None:
        self._repository: IRedemptionRepository = repository
        self._registrations: IRegistrationRepository = registrations
        self._sessions: ISessionRepository = sessions
        self._provisioner: IAccountProvisioner = provisioner
        self._audit: IMemberJoinAuditWriter = audit

    async def _valid(
        self, invitation: Invitation | None, token: str, now: datetime, *, accepted: bool = False
    ) -> Invitation:
        token_hash = supplied_token_hash(token)
        if (
            invitation is None
            or invitation.expires_at <= now
            or token_hash is None
            or not secrets.compare_digest(invitation.token_hash, token_hash)
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

    async def _read(
        self, invitation_id: UUID, token: str, now: datetime, *, accepted: bool = False
    ) -> InvitationLink:
        link = await self._repository.find(invitation_id)
        if link is None:
            raise UseCaseError(Failure.LINK_INVALID)
        await self._valid(link.invitation, token, now, accepted=accepted)
        return link

    async def _locked(
        self, invitation_id: UUID, token: str, now: datetime, *, accepted: bool = False
    ) -> Invitation:
        return await self._valid(
            await self._repository.lock(invitation_id), token, now, accepted=accepted
        )

    async def preview(self, invitation_id: UUID, token: str, now: datetime) -> InvitationPreview:
        link = await self._read(invitation_id, token, now)
        return InvitationPreview(
            link.invitation,
            link.workspace_name,
            await self._repository.account_exists(link.invitation.invited_email),
        )

    async def accept(
        self, invitation_id: UUID, token: str, user_id: UUID, email: str, now: datetime
    ) -> WorkspaceMembership:
        await self._read(invitation_id, token, now, accepted=True)
        invitation = await self._locked(invitation_id, token, now, accepted=True)
        if email.lower() != invitation.invited_email.lower():
            raise UseCaseError(
                Failure.LINK_INVALID
                if invitation.status is InvitationStatus.ACCEPTED
                else Failure.EMAIL_MISMATCH
            )
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
        await self._read(invitation_id, token, now)
        invitation = await self._locked(invitation_id, token, now)
        await self._repository.answer(invitation, InvitationStatus.DECLINED, now)
        return invitation

    async def register(
        self, invitation_id: UUID, token: str, details: RegistrationDetails, now: datetime
    ) -> tuple[SignedIn, WorkspaceMembership]:
        candidate = await self._read(invitation_id, token, now)
        # Share registration's email lock before taking any workspace locks.
        await self._registrations.lock_email(candidate.invitation.invited_email)
        invitation = await self._locked(invitation_id, token, now)
        if await self._sessions.by_email(invitation.invited_email) is not None:
            raise UseCaseError(Failure.ACCOUNT_EXISTS)
        signed = await self._provisioner.provision(invitation.invited_email, details, now)
        member = await self._join(invitation, signed.user.user_id, now)
        return signed, member
