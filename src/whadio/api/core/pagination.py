import base64
import binascii
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from ...shared.errors import Failure, UseCaseError
from ...shared.pagination import ListCursor, ListWindow
from .schemas import Page, PageInfo, PageQuery


class ListToken(BaseModel):
    scope: str = Field(description="Resource and ordering this cursor belongs to")
    key: str = Field(max_length=2001, description="Last item's sort key")
    item_id: UUID = Field(description="Last item's identifier")


def list_window(query: PageQuery, scope: str, *, chronological: bool = False) -> ListWindow:
    after = None
    if query.cursor is not None:
        try:
            encoded = query.cursor + "=" * (-len(query.cursor) % 4)
            token = ListToken.model_validate_json(
                base64.b64decode(encoded, altchars=b"-_", validate=True)
            )
            _validate_token(token, scope, chronological=chronological)
            after = ListCursor(token.key, token.item_id)
        except (ValueError, ValidationError, binascii.Error):
            raise UseCaseError(Failure.VALIDATION_ERROR) from None
    return ListWindow(query.limit + 1, after)


def _validate_token(token: ListToken, scope: str, *, chronological: bool) -> None:
    if token.scope != scope:
        raise ValueError("Cursor belongs to another list")
    if chronological:
        timestamp = datetime.fromisoformat(token.key)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Cursor requires an aware timestamp")


def list_page[T](items: list[T], query: PageQuery, scope: str, last: ListCursor | None) -> Page[T]:
    has_more = len(items) > query.limit
    token = None
    if has_more and last is not None:
        value = ListToken(scope=scope, key=last.key, item_id=last.item_id)
        token = base64.urlsafe_b64encode(value.model_dump_json().encode()).decode().rstrip("=")
    return Page(
        items=items[: query.limit],
        pagination=PageInfo(limit=query.limit, next_cursor=token, has_more=has_more),
    )
