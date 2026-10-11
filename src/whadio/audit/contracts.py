from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .enums import AuditAction


@dataclass(frozen=True)
class ContentEvent:
    actor_id: UUID
    workspace_id: UUID
    meeting_id: UUID
    action: AuditAction
    occurred_at: datetime
    subject_id: UUID | None = None
    from_folder_id: UUID | None = None
    to_folder_id: UUID | None = None
    requester_id: UUID | None = None


class IContentAuditWriter(Protocol):
    async def write(self, event: ContentEvent) -> None:
        """Persist the event in the caller's transaction; failure must abort the change."""
        ...
