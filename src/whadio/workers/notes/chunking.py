from collections.abc import Sequence

from ...contracts.common import Segment


def chunk_segments(segments: Sequence[Segment], max_chars: int) -> list[tuple[Segment, ...]]:
    if not segments:
        return []

    chunks: list[tuple[Segment, ...]] = []
    current_chunk: list[Segment] = []
    current_chunk_length = 0
    for s in segments:
        s_length = len(s.text)

        if s_length > max_chars:
            chunks.append(tuple(current_chunk))
            current_chunk = [s]
        elif s_length + current_chunk_length <= max_chars:
            current_chunk.append(s)
            current_chunk_length += s_length
            continue

        chunks.append(tuple(current_chunk))
        current_chunk_length = 0
        current_chunk = [s]

    if current_chunk:
        chunks.append(tuple(current_chunk))

    return chunks
