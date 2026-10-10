import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, Final

import av
import httpx2
import numpy as np
from av.audio.frame import AudioFrame
from av.audio.stream import AudioStream
from av.container import InputContainer
from av.error import FFmpegError, InvalidDataError
from numpy.typing import NDArray

from ...contracts.transcription import AudioLink, TranscriptionFailure
from .errors import TranscriptionError

SAMPLE_RATE: Final = 16_000
_FORBIDDEN: Final = 403
_NOT_FOUND: Final = 404


@dataclass(frozen=True, slots=True, eq=False)
class Audio:
    """Mono speech at `SAMPLE_RATE`, the rate every model of the pipeline takes."""

    samples: NDArray[np.float32]

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / SAMPLE_RATE


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AudioFetcher:
    def __init__(
        self,
        client: httpx2.Client,
        *,
        max_bytes: int,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client: httpx2.Client = client
        self._max_bytes: int = max_bytes
        self._now: Callable[[], datetime] = now

    def fetch(self, link: AudioLink, sink: BinaryIO) -> None:
        if link.expires_at <= self._now():
            raise TranscriptionError(TranscriptionFailure.AUDIO_LINK_EXPIRED)
        try:
            with self._client.stream("GET", str(link.url)) as response:
                self._check(response)
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > self._max_bytes:
                        raise TranscriptionError(TranscriptionFailure.AUDIO_TOO_LARGE)
                    sink.write(chunk)
        except httpx2.TransportError as error:
            raise TranscriptionError(TranscriptionFailure.STORAGE_UNAVAILABLE) from error

    def _check(self, response: httpx2.Response) -> None:
        # S3 answers 403 to an expired presigned URL; Processing then signs a new one.
        if response.status_code == _FORBIDDEN:
            raise TranscriptionError(TranscriptionFailure.AUDIO_LINK_EXPIRED)
        if response.status_code == _NOT_FOUND:
            raise TranscriptionError(TranscriptionFailure.AUDIO_NOT_FOUND)
        if not response.is_success:
            raise TranscriptionError(TranscriptionFailure.STORAGE_UNAVAILABLE)
        length = response.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > self._max_bytes:
            raise TranscriptionError(TranscriptionFailure.AUDIO_TOO_LARGE)


class AudioDecoder:
    def __init__(self, *, max_duration: timedelta) -> None:
        self._max_seconds: float = max_duration.total_seconds()

    def decode(self, source: BinaryIO) -> Audio:
        try:
            with av.open(source, mode="r") as container:
                if not container.streams.audio:
                    raise TranscriptionError(TranscriptionFailure.UNSUPPORTED_AUDIO)
                if (
                    container.duration is not None
                    and container.duration / av.time_base > self._max_seconds
                ):
                    raise TranscriptionError(TranscriptionFailure.AUDIO_TOO_LONG)
                chunks = self._mono_chunks(container, container.streams.audio[0])
        except FFmpegError as error:
            raise TranscriptionError(TranscriptionFailure.UNSUPPORTED_AUDIO) from error
        if not chunks:
            raise TranscriptionError(TranscriptionFailure.UNSUPPORTED_AUDIO)
        return Audio(np.concatenate(chunks))

    def _mono_chunks(
        self, container: InputContainer, stream: AudioStream
    ) -> list[NDArray[np.float32]]:
        max_samples = self._max_seconds * SAMPLE_RATE
        chunks: list[NDArray[np.float32]] = []
        count = 0
        for frame in _resampled(container, stream):
            chunk = np.asarray(frame.to_ndarray(), dtype=np.float32).reshape(-1)
            count += chunk.size
            if count > max_samples:
                raise TranscriptionError(TranscriptionFailure.AUDIO_TOO_LONG)
            if chunk.size:
                chunks.append(chunk)
        return chunks


def _resampled(container: InputContainer, stream: AudioStream) -> Iterator[AudioFrame]:
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    for packet in container.demux(stream):
        try:
            frames = packet.decode()
        except InvalidDataError:
            # Recordings, MP3 files above all, often hold a few corrupt frames; the rest is usable.
            continue
        for frame in frames:
            yield from resampler.resample(frame)
    yield from resampler.resample(None)


class AudioLoader:
    def __init__(self, fetcher: AudioFetcher, decoder: AudioDecoder) -> None:
        self._fetcher: AudioFetcher = fetcher
        self._decoder: AudioDecoder = decoder

    def load(self, link: AudioLink) -> Audio:
        with tempfile.TemporaryFile() as recording:
            self._fetcher.fetch(link, recording)
            recording.seek(0)
            return self._decoder.decode(recording)
