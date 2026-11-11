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
    "scope", [_SCOPE, "workspaces:1:created", "capture-destinations:1:created"]
)
@given(
    key=st.text(max_size=_LONGEST_KEY),
    item_id=st.uuids(),
    limit=st.integers(min_value=1, max_value=100),
)
def test_next_cursor_decodes_to_the_last_item_of_the_page(
    scope: str, key: str, item_id: UUID, limit: int
) -> None:
    # Arrange
    last = ListCursor(key, item_id)
    page = list_page(list(range(limit + 1)), PageQuery(limit=limit), scope, last)

    # Act
    window = list_window(PageQuery(limit=limit, cursor=page.pagination.next_cursor), scope)

    # Assert
    assert window.after == last
