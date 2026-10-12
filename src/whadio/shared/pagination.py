from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ListCursor:
    key: str
    item_id: UUID


@dataclass(frozen=True)
class ListWindow:
    limit: int
    after: ListCursor | None = None
