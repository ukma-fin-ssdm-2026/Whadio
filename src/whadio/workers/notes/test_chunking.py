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


@pytest.mark.parametrize(
    ("texts", "max_chars", "length"),
    [
        pytest.param(["111", "22"], 5, 1, id="no-overflow-on-the-edge"),
        pytest.param(["111", "222"], 5, 2, id="overflow"),
    ],
)
def test_segment_that_overflows_starts_a_new_chunk(
    texts: list[str], max_chars: int, length: int
) -> None:
    # Arrange
    segments = [
        Segment(start_seconds=i, end_seconds=i + 1, speaker=f"speaker_{i}", text=t)
        for i, t in enumerate(texts)
    ]

    # Act
    chunks = chunk_segments(segments, max_chars)

    # Assert
    assert len(chunks) == length
