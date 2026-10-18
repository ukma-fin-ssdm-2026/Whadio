from collections.abc import Sequence

from ...contracts.common import Segment


def chunk_segments(segments: Sequence[Segment], max_chars: int) -> list[tuple[Segment, ...]]:
    del segments
    del max_chars
    return []
