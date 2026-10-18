from typing import TYPE_CHECKING

import pytest

from .chunking import chunk_segments

if TYPE_CHECKING:
    from ...contracts.common import Segment


@pytest.mark.xfail(strict=True, raises=NotImplementedError)
def test_no_segments_give_no_chunks() -> None:
    # Arrange
    segments: list[Segment] = []

    # Act
    chunks = chunk_segments(segments, 10)

    # Assert
    assert len(chunks) == 0
