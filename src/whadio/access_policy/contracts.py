from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class MeetingScope:
    meeting_id: UUID
    workspace_id: UUID
    creator_id: UUID
    restricted: bool


class IMeetingAccessSource(Protocol):
    async def scope(self, meeting_id: UUID, *, lock: bool = False) -> MeetingScope: ...

    async def set_restricted(self, meeting_id: UUID, *, restricted: bool) -> None: ...
