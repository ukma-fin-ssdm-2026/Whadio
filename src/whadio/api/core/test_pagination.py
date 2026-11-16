from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ...shared.pagination import ListCursor
from .pagination import list_page, list_window
from .schemas import PageQuery

_SCOPE: Final = f"glossary:{UUID(int=1)}:{UUID(int=2)}"
# Sort keys come from names of at most 200 characters, which lowercasing can double. Much longer
# keys of escaped or astral characters outgrow the 4096-character cursor that PageQuery accepts.
_LONGEST_KEY: Final = 400


@pytest.mark.parametrize(
    ("scope", "chronological"),
    [
        (_SCOPE, False),
        (f"workspaces:{UUID(int=1)}:joined", True),
        (f"capture-destinations:{UUID(int=1)}:joined", True),
    ],
)
@given(
    data=st.data(),
    item_id=st.uuids(),
    limit=st.integers(min_value=1, max_value=100),
)
def test_next_cursor_decodes_to_the_last_item_of_the_page(
    scope: str, data: st.DataObject, item_id: UUID, limit: int, *, chronological: bool
) -> None:
    # Arrange
    keys = (
        st.datetimes(timezones=st.just(UTC)).map(datetime.isoformat)
        if chronological
        else st.text(max_size=_LONGEST_KEY)
    )
    key = data.draw(keys)
    last = ListCursor(key, item_id)
    page = list_page(list(range(limit + 1)), PageQuery(limit=limit), scope, last)

    # Act
    window = list_window(
        PageQuery(limit=limit, cursor=page.pagination.next_cursor),
        scope,
        chronological=chronological,
    )

    # Assert
    assert window.after == last
