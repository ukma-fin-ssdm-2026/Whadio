import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select

from ..accounts.contracts import UserProfile
from ..accounts.enums import WorkspaceRole
from ..accounts.services import IWorkspaceDirectory
from ..audit.contracts import ContentEvent, IContentAuditWriter
from ..audit.enums import AuditAction
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .contracts import IMeetingAccessSource, MeetingScope
from .enums import ShareRequestStatus
from .models import ExternalShare, MeetingAccessGrant, ShareAccessRequest
from .repositories import IAccessRepository


class ContentPath(StrEnum):
    READ = "read"
    EXPORT = "export"
    MCP = "mcp"
    RECORDING = "recording"
    WRITE = "write"


@dataclass(frozen=True)
class Permission:
    role: WorkspaceRole | None
    redact_speaker_names: bool = False
    meeting_id: UUID | None = None


@dataclass(frozen=True)
class CreatedShare:
    share: ExternalShare
    token: str


class IShareRequestNotifier(Protocol):
    async def enqueue(self, share_id: UUID, creator_id: UUID, requester_id: UUID) -> None:
        """Persist the notice in the caller's transaction; do not send email before commit."""
        ...


class IMeetingPolicy(Protocol):
    def granted_meetings(self, user_id: UUID) -> Select[UUID]: ...

    async def workspace_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole: ...

    async def authorize(self, scope: MeetingScope, user_id: UUID) -> Permission: ...

    async def authorize_share(
        self, share_id: UUID, user_id: UUID, path: ContentPath
    ) -> Permission: ...


class IRetentionAccess(Protocol):
    async def recipients(self, scope: MeetingScope) -> list[UUID]: ...


class AccessPolicy:
    def __init__(self, repository: IAccessRepository, memberships: IWorkspaceDirectory) -> None:
        self._repository: IAccessRepository = repository
        self._memberships: IWorkspaceDirectory = memberships

    def granted_meetings(self, user_id: UUID) -> Select[UUID]:
        return self._repository.granted_meetings(user_id)

    async def workspace_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole:
        role = await self._memberships.role(workspace_id, user_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return role

    async def authorize(self, scope: MeetingScope, user_id: UUID) -> Permission:
        role = await self.workspace_role(scope.workspace_id, user_id)
        if scope.restricted and user_id not in await self._repository.grants(scope.meeting_id):
            raise UseCaseError(Failure.NOT_FOUND)
        return Permission(role, meeting_id=scope.meeting_id)

    async def authorize_share(self, share_id: UUID, user_id: UUID, path: ContentPath) -> Permission:
        share = await self._repository.share(share_id)
        if share is None or share.recipient_user_id != user_id:
            raise UseCaseError(Failure.NOT_FOUND)
        if share.revoked_at is not None:
            raise UseCaseError(Failure.SHARE_REVOKED)
        if path != ContentPath.READ:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        return Permission(None, share.redact_speaker_names, share.meeting_id)

    async def recipients(self, scope: MeetingScope) -> list[UUID]:
        members = await self._memberships.members(scope.workspace_id)
        if not scope.restricted:
            return members
        granted = await self._repository.grants(scope.meeting_id)
        return [user_id for user_id in members if user_id in granted]


@dataclass(frozen=True)
class AccessCollaborators:
    repository: IAccessRepository
    meetings: IMeetingAccessSource
    memberships: IWorkspaceDirectory
    audit: IContentAuditWriter
    notifications: IShareRequestNotifier


class AccessService:
    def __init__(self, collaborators: AccessCollaborators) -> None:
        self._dependencies: AccessCollaborators = collaborators
        self.policy: AccessPolicy = AccessPolicy(
            collaborators.repository, collaborators.memberships
        )

    async def requester_profile(self, actor_id: UUID, request_id: UUID) -> UserProfile:
        request = await self._dependencies.repository.request(request_id)
        if request is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if request.requester_user_id != actor_id:
            share = await self._dependencies.repository.share(request.share_id)
            if share is None:
                raise UseCaseError(Failure.NOT_FOUND)
            await self._creator(share, actor_id)
        profile = await self._dependencies.memberships.profile(request.requester_user_id)
        if profile is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return profile

    async def read_access(self, actor_id: UUID, meeting_id: UUID) -> tuple[bool, set[UUID]]:
        scope = await self._dependencies.meetings.scope(meeting_id)
        await self.policy.authorize(scope, actor_id)
        return scope.restricted, await self._dependencies.repository.grants(meeting_id)

    async def shares(
        self, actor_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[ExternalShare]:
        scope = await self._dependencies.meetings.scope(meeting_id)
        await self.policy.authorize(scope, actor_id)
        return await self._dependencies.repository.shares(meeting_id, page)

    async def recipient_shares(self, actor_id: UUID, page: ListWindow) -> list[ExternalShare]:
        return await self._dependencies.repository.recipient_shares(actor_id, page)

    async def requests(
        self, actor_id: UUID, share_id: UUID, page: ListWindow | None = None
    ) -> list[ShareAccessRequest]:
        share = await self._dependencies.repository.share(share_id)
        if share is None:
            raise UseCaseError(Failure.NOT_FOUND)
        await self._creator(share, actor_id)
        return await self._dependencies.repository.requests(share_id, page)

    async def replace_access(
        self,
        actor_id: UUID,
        meeting_id: UUID,
        member_ids: set[UUID],
        now: datetime,
        *,
        restricted: bool,
    ) -> None:
        dependencies = self._dependencies
        scope = await dependencies.meetings.scope(meeting_id, lock=True)
        permission = await self.policy.authorize(scope, actor_id)
        if permission.role is None or permission.role not in (
            WorkspaceRole.OWNER,
            WorkspaceRole.MODERATOR,
        ):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        if (restricted and not member_ids) or (not restricted and member_ids):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        for user_id in sorted(member_ids):
            if await dependencies.memberships.role(scope.workspace_id, user_id) is None:
                raise UseCaseError(Failure.VALIDATION_ERROR)
        previous = await dependencies.repository.grants(meeting_id)
        await dependencies.meetings.set_restricted(meeting_id, restricted=restricted)
        await dependencies.repository.replace_grants(
            meeting_id,
            [
                MeetingAccessGrant(
                    access_grant_id=uuid4(),
                    meeting_id=meeting_id,
                    user_id=user_id,
                    granted_by_user_id=actor_id,
                    granted_at=now,
                )
                for user_id in sorted(member_ids)
            ],
        )
        if restricted != scope.restricted:
            await dependencies.audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.MEETING_RESTRICTED
                    if restricted
                    else AuditAction.MEETING_UNRESTRICTED,
                    now,
                )
            )
        if restricted:
            for user_id in sorted(member_ids - previous):
                await dependencies.audit.write(
                    ContentEvent(
                        actor_id,
                        scope.workspace_id,
                        meeting_id,
                        AuditAction.ACCESS_GRANTED,
                        now,
                        user_id,
                    )
                )
            for user_id in sorted(previous - member_ids):
                await dependencies.audit.write(
                    ContentEvent(
                        actor_id,
                        scope.workspace_id,
                        meeting_id,
                        AuditAction.ACCESS_REVOKED,
                        now,
                        user_id,
                    )
                )

    async def create_share(
        self,
        actor_id: UUID,
        meeting_id: UUID,
        now: datetime,
        *,
        redact: bool,
    ) -> CreatedShare:
        dependencies = self._dependencies
        scope = await dependencies.meetings.scope(meeting_id, lock=True)
        await self.policy.authorize(scope, actor_id)
        token = secrets.token_urlsafe(32)
        share = ExternalShare(
            share_id=uuid4(),
            meeting_id=meeting_id,
            created_by_user_id=actor_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            redact_speaker_names=redact,
            created_at=now,
            recipient_user_id=None,
            revoked_at=None,
        )
        await dependencies.repository.save_share(share)
        await dependencies.audit.write(
            ContentEvent(
                actor_id,
                scope.workspace_id,
                meeting_id,
                AuditAction.SHARE_CREATED,
                now,
                share.share_id,
            )
        )
        return CreatedShare(share, token)

    async def request_access(
        self,
        actor_id: UUID,
        share_id: UUID,
        token: str,
        now: datetime,
    ) -> ShareAccessRequest:
        dependencies = self._dependencies
        share = await dependencies.repository.share(share_id, lock=True)
        if (
            share is None
            or share.revoked_at is not None
            or not secrets.compare_digest(
                share.token_hash, hashlib.sha256(token.encode()).hexdigest()
            )
        ):
            raise UseCaseError(Failure.LINK_INVALID)
        scope = await dependencies.meetings.scope(share.meeting_id)
        role = await dependencies.memberships.role(scope.workspace_id, actor_id)
        if share.recipient_user_id == actor_id or (
            role is not None
            and (
                not scope.restricted
                or actor_id in await dependencies.repository.grants(scope.meeting_id)
            )
        ):
            raise UseCaseError(Failure.ALREADY_HAS_ACCESS)
        if await dependencies.repository.requested(share_id, actor_id):
            raise UseCaseError(Failure.ACCESS_REQUEST_EXISTS)
        request = ShareAccessRequest(
            share_access_request_id=uuid4(),
            share_id=share_id,
            requester_user_id=actor_id,
            status=ShareRequestStatus.PENDING,
            requested_at=now,
            decided_at=None,
        )
        await dependencies.repository.save_request(request)
        await dependencies.notifications.enqueue(share_id, share.created_by_user_id, actor_id)
        return request

    async def decide(
        self,
        actor_id: UUID,
        request_id: UUID,
        now: datetime,
        *,
        approve: bool,
    ) -> ShareAccessRequest:
        dependencies = self._dependencies
        request = await dependencies.repository.request(request_id)
        if request is None:
            raise UseCaseError(Failure.NOT_FOUND)
        share = await dependencies.repository.share(request.share_id, lock=True)
        if share is None:
            raise UseCaseError(Failure.NOT_FOUND)
        request = await dependencies.repository.request(request_id)
        if request is None:
            raise UseCaseError(Failure.NOT_FOUND)
        scope = await self._creator(share, actor_id)
        if request.status != "pending":
            raise UseCaseError(Failure.ACCESS_REQUEST_NOT_PENDING)
        if approve and share.revoked_at is not None:
            raise UseCaseError(Failure.SHARE_REVOKED)
        if approve and share.recipient_user_id is not None:
            raise UseCaseError(Failure.SHARE_ALREADY_BOUND)
        if approve:
            share.recipient_user_id = request.requester_user_id
            await dependencies.repository.save_share(share)
        request.status = ShareRequestStatus.APPROVED if approve else ShareRequestStatus.DECLINED
        request.decided_at = now
        await dependencies.repository.save_request(request)
        await dependencies.audit.write(
            ContentEvent(
                actor_id,
                scope.workspace_id,
                scope.meeting_id,
                AuditAction.SHARE_ACCESS_APPROVED if approve else AuditAction.SHARE_ACCESS_DECLINED,
                now,
                share.share_id,
                requester_id=request.requester_user_id,
            )
        )
        return request

    async def revoke(self, actor_id: UUID, share_id: UUID, now: datetime) -> None:
        dependencies = self._dependencies
        share = await dependencies.repository.share(share_id, lock=True)
        if share is None:
            raise UseCaseError(Failure.NOT_FOUND)
        scope = await self._creator(share, actor_id)
        if share.revoked_at is not None:
            return
        share.revoked_at = now
        await dependencies.repository.save_share(share)
        await dependencies.audit.write(
            ContentEvent(
                actor_id,
                scope.workspace_id,
                scope.meeting_id,
                AuditAction.SHARE_REVOKED,
                now,
                share_id,
            )
        )

    async def _creator(self, share: ExternalShare, actor_id: UUID) -> MeetingScope:
        scope = await self._dependencies.meetings.scope(share.meeting_id)
        await self.policy.authorize(scope, actor_id)
        if share.created_by_user_id != actor_id:
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        return scope
