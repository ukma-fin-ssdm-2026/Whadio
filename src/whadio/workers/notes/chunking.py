from collections.abc import Sequence

from ...contracts.common import Segment


def chunk_segments(segments: Sequence[Segment], max_chars: int) -> list[tuple[Segment, ...]]:
    if not segments:
        return []
    if max_chars < 1:
        raise ValueError(f"max_chars must be at least 1, got {max_chars}")

    chunks: list[tuple[Segment, ...]] = []
    current: list[Segment] = []
    current_size = 0
    for segment in segments:
        size = _size(segment)
        if size > max_chars:
            if current:
                chunks.append(tuple(current))
            chunks.append((segment,))
            current = []
            current_size = 0
        elif current_size + size <= max_chars:
            current.append(segment)
            current_size += size
        else:
            chunks.append(tuple(current))
            current = [segment]
            current_size = size

    if current:
        chunks.append(tuple(current))
    return chunks


def _size(segment: Segment) -> int:
    return len(segment.text)
