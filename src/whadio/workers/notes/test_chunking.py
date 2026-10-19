import pytest

from ...contracts.common import Segment
from .chunking import chunk_segments


def _segments(*texts: str) -> list[Segment]:
    return [
        Segment(start_seconds=i, end_seconds=i + 1, speaker=None, text=text)
        for i, text in enumerate(texts)
    ]


def test_no_segments_give_no_chunks() -> None:
    # Arrange
    segments: list[Segment] = []

    # Act
    chunks = chunk_segments(segments, 10)

    # Assert
    assert chunks == []


def test_segments_within_the_limit_form_one_chunk() -> None:
    # Arrange
    segments = _segments("Under", "Ten")

    # Act
    chunks = chunk_segments(segments, 10)

    # Assert
    assert chunks == [(segments[0], segments[1])]


@pytest.mark.parametrize(
    ("texts", "max_chars", "groups"),
    [
        pytest.param(("111", "22"), 5, ((0, 1),), id="bva-at-limit"),
        pytest.param(("111", "222"), 5, ((0,), (1,)), id="bva-over-limit"),
    ],
)
def test_segment_that_overflows_starts_a_new_chunk(
    texts: tuple[str, ...], max_chars: int, groups: tuple[tuple[int, ...], ...]
) -> None:
    # Arrange
    segments = _segments(*texts)

    # Act
    chunks = chunk_segments(segments, max_chars)

    # Assert
    assert chunks == [tuple(segments[i] for i in group) for group in groups]


def test_oversized_segment_becomes_its_own_chunk() -> None:
    # Arrange
    segments = _segments("111", "2", "333333", "2")

    # Act
    chunks = chunk_segments(segments, 5)

    # Assert
    assert chunks == [(segments[0], segments[1]), (segments[2],), (segments[3],)]


@pytest.mark.parametrize(
    "max_chars", [pytest.param(-1, id="bva-below-zero"), pytest.param(0, id="bva-zero")]
)
def test_non_positive_limit_is_refused(max_chars: int) -> None:
    # Arrange
    segments = _segments("Under", "Ten")

    # Act / Assert
    with pytest.raises(ValueError, match="max_chars"):
        chunk_segments(segments, max_chars)


def test_limit_of_one_is_accepted() -> None:
    # Arrange
    segments = _segments("Under", "Ten")

    # Act
    chunks = chunk_segments(segments, 1)

    # Assert
    assert chunks == [(segments[0],), (segments[1],)]


def test_chunk_after_an_overflow_counts_its_first_segment() -> None:
    # Arrange
    segments = _segments("aaaaaa", "bbbbbb", "cccccc")

    # Act
    chunks = chunk_segments(segments, 10)

    # Assert
    assert chunks == [(segments[0],), (segments[1],), (segments[2],)]


@pytest.mark.xfail(strict=True, raises=pytest.fail.Exception)
def test_max_chars_check_comes_before_empty_segments_check() -> None:
    # Arrange
    segments: list[Segment] = []
    max_chars = -1

    # Act & Assert
    with pytest.raises(ValueError, match=r"^max_chars must be at least 1, got [\-]?\d+$"):
        chunk_segments(segments, max_chars)
