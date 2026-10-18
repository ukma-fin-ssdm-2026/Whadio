import pytest

from ...contracts.common import Segment
from .chunking import chunk_segments


def test_no_segments_give_no_chunks() -> None:
    # Arrange
    segments: list[Segment] = []

    # Act
    chunks = chunk_segments(segments, 10)

    # Assert
    assert len(chunks) == 0


@pytest.mark.xfail(strict=True, raises=AssertionError)
def test_segments_within_the_limit_form_one_chunk() -> None:
    # Arrange
    max_chars = 10
    segments = [
        Segment(start_seconds=0.0, end_seconds=1.0, speaker="speaker_0", text="Under"),
        Segment(start_seconds=1.0, end_seconds=2.0, speaker="speaker_1", text="Ten"),
    ]

    # Act
    chunks = chunk_segments(segments, max_chars)

    # Assert
    assert len(chunks) == 1
