from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field

from .errors import ApiError, ErrorCode, ErrorDetail


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Output(BaseModel):
    pass


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class PageQuery(Input):
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of items to return")
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Opaque `next_cursor` from the previous page; omit for the first page",
    )


class PageInfo(Output):
    limit: int = Field(description="Page size that was applied", examples=[20])
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page",
        examples=["20"],
    )
    has_more: bool = Field(description="Whether another page follows", examples=[False])


class Page[T](Output):
    items: list[T] = Field(description="Items of this page, in the documented order")
    pagination: PageInfo


def paginate[T](items: Sequence[T], query: PageQuery) -> Page[T]:
    # Stub cursor: the position of the next item. The design's cursor is an opaque sort key.
    start = 0
    if query.cursor is not None:
        if not query.cursor.isdigit() or not 0 < int(query.cursor) < len(items):
            raise ApiError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request contains invalid fields",
                [ErrorDetail(field="cursor", message="is not a cursor of this list")],
            )
        start = int(query.cursor)
    end = start + query.limit
    has_more = end < len(items)
    return Page[T](
        items=list(items[start:end]),
        pagination=PageInfo(
            limit=query.limit, next_cursor=str(end) if has_more else None, has_more=has_more
        ),
    )
