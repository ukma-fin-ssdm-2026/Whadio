from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import ContentEvent
from .enums import AuditAction
from .models import AuditEvent


@dataclass(frozen=True)
class MeetingMoved:
    actor_id: UUID
    workspace_id: UUID
    meeting_id: UUID
    occurred_at: datetime
    from_folder_id: UUID
    to_folder_id: UUID


@dataclass(frozen=True)
class WorkspaceDeleted:
    actor_id: UUID
    workspace_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class MemberInvited:
    actor_id: UUID
    workspace_id: UUID
    invitation_id: UUID
    role: str
    occurred_at: datetime


@dataclass(frozen=True)
class InvitationCancelled:
    actor_id: UUID
    workspace_id: UUID
    invitation_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class McpKeyCreated:
    actor_id: UUID
    key_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class McpKeyRevoked:
    actor_id: UUID
    key_id: UUID
    occurred_at: datetime


class IAccountAuditWriter(Protocol):
    async def write(self, event: McpKeyCreated | McpKeyRevoked) -> None: ...


class IAuditWriter(Protocol):
    async def write(self, event: MeetingMoved) -> None: ...


class IWorkspaceAuditWriter(Protocol):
    async def write(self, event: WorkspaceDeleted) -> None: ...


class IInvitationAuditWriter(Protocol):
    async def write(self, event: MemberInvited | InvitationCancelled) -> None: ...


class AuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def write(
        self,
        event: (
            MeetingMoved
            | WorkspaceDeleted
            | MemberInvited
            | InvitationCancelled
            | McpKeyCreated
            | McpKeyRevoked
            | ContentEvent
        ),
    ) -> None:
        if isinstance(event, (McpKeyCreated, McpKeyRevoked)):
            self._session.add(
                AuditEvent(
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_id,
                    action=(
                        AuditAction.MCP_KEY_CREATED
                        if isinstance(event, McpKeyCreated)
                        else AuditAction.MCP_KEY_REVOKED
                    ),
                    subject_id=event.key_id,
                )
            )
            await self._session.flush()
            return
        if isinstance(event, WorkspaceDeleted):
            self._session.add(
                AuditEvent(
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_id,
                    action=AuditAction.WORKSPACE_DELETED,
                    workspace_id=event.workspace_id,
                )
            )
            await self._session.flush()
            return
        if isinstance(event, (MemberInvited, InvitationCancelled)):
            self._session.add(
                AuditEvent(
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_id,
                    action=(
                        AuditAction.MEMBER_INVITED
                        if isinstance(event, MemberInvited)
                        else AuditAction.INVITATION_CANCELLED
                    ),
                    workspace_id=event.workspace_id,
                    subject_id=event.invitation_id,
                    details=({"role": event.role} if isinstance(event, MemberInvited) else None),
                )
            )
            await self._session.flush()
            return
        if isinstance(event, MeetingMoved):
            event = ContentEvent(
                event.actor_id,
                event.workspace_id,
                event.meeting_id,
                AuditAction.MEETING_MOVED,
                event.occurred_at,
                from_folder_id=event.from_folder_id,
                to_folder_id=event.to_folder_id,
            )
        details = {
            key: str(value)
            for key, value in (
                ("from_folder_id", event.from_folder_id),
                ("to_folder_id", event.to_folder_id),
                ("requester_user_id", event.requester_id),
                ("meeting_id", event.triggering_meeting_id),
                ("preset", event.preset),
            )
            if value is not None
        }
        self._session.add(
            AuditEvent(
                occurred_at=event.occurred_at,
                actor_user_id=event.actor_id,
                action=event.action,
                workspace_id=event.workspace_id,
                meeting_id=event.meeting_id,
                subject_id=event.subject_id,
                details=details or None,
            )
        )
        await self._session.flush()
