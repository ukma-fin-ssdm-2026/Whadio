from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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


class IAuditWriter(Protocol):
    async def write(self, event: MeetingMoved) -> None: ...


class AuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def write(self, event: MeetingMoved) -> None:
        self._session.add(
            AuditEvent(
                occurred_at=event.occurred_at,
                actor_user_id=event.actor_id,
                action=AuditAction.MEETING_MOVED,
                workspace_id=event.workspace_id,
                meeting_id=event.meeting_id,
                details={
                    "from_folder_id": str(event.from_folder_id),
                    "to_folder_id": str(event.to_folder_id),
                },
            )
        )
        await self._session.flush()
