import io
import wave
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import HttpUrl

from ...contracts.transcription import AudioLink, TranscriptionFailure
from .audio import SAMPLE_RATE, Audio, AudioDecoder, AudioFetcher, AudioLoader
from .errors import TranscriptionError

type _Handler = Callable[[httpx2.Request], httpx2.Response]

_NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
_LINK = AudioLink(
    url=HttpUrl("http://storage.test/recordings/a.flac?X-Amz-Signature=abc"),
    expires_at=_NOW + timedelta(minutes=10),
)
_TESTDATA = Path(__file__).parent / "testdata"
_CLIP = _TESTDATA / "en-2277-149896-0032.flac"
_LIVE_WEBM = _TESTDATA / "tone-live.webm"
_LIMIT = timedelta(minutes=1)


def _tone(seconds: float, rate: int) -> NDArray[np.int16]:
    times = np.arange(int(seconds * rate)) / rate
    return (0.2 * 32767 * np.sin(2 * np.pi * 440 * times)).astype(np.int16)


def _wav(samples: NDArray[np.int16], *, rate: int = 44_100, channels: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(channels)
        recording.setsampwidth(2)
        recording.setframerate(rate)
        recording.writeframes(np.repeat(samples, channels).tobytes())
    return buffer.getvalue()


def _answering(status: int, content: bytes = b"") -> _Handler:
    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=content)

    return handle


def _fetch(handler: _Handler, *, max_bytes: int = 1_000, link: AudioLink = _LINK) -> bytes:
    sink = io.BytesIO()
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        AudioFetcher(client, max_bytes=max_bytes, now=lambda: _NOW).fetch(link, sink)
    return sink.getvalue()


def _fetch_failure(handler: _Handler, *, max_bytes: int = 1_000) -> TranscriptionFailure:
    with pytest.raises(TranscriptionError) as raised:
        _fetch(handler, max_bytes=max_bytes)
    return raised.value.reason


def _decode(data: bytes, *, max_duration: timedelta = _LIMIT) -> Audio:
    return AudioDecoder(max_duration=max_duration).decode(io.BytesIO(data))


def _decode_failure(data: bytes, *, max_duration: timedelta = _LIMIT) -> TranscriptionFailure:
    with pytest.raises(TranscriptionError) as raised:
        _decode(data, max_duration=max_duration)
    return raised.value.reason


# --- Fetching ---


def test_fetcher_writes_the_recording_to_the_sink() -> None:
    # Arrange
    handler = _answering(200, b"recording bytes")

    # Act
    fetched = _fetch(handler)

    # Assert
    assert fetched == b"recording bytes"


def test_fetcher_keeps_a_recording_exactly_at_the_size_limit() -> None:
    # Arrange
    handler = _answering(200, b"x" * 1_000)

    # Act
    fetched = _fetch(handler, max_bytes=1_000)

    # Assert
    assert len(fetched) == 1_000


def test_fetcher_reports_a_refused_link_as_expired() -> None:
    # Act
    reason = _fetch_failure(_answering(403))

    # Assert
    assert reason is TranscriptionFailure.AUDIO_LINK_EXPIRED


def test_fetcher_reports_a_missing_recording_as_not_found() -> None:
    # Act
    reason = _fetch_failure(_answering(404))

    # Assert
    assert reason is TranscriptionFailure.AUDIO_NOT_FOUND


@pytest.mark.parametrize("status", [400, 500, 503])
def test_fetcher_reports_other_failed_answers_as_storage_unavailable(status: int) -> None:
    # Act
    reason = _fetch_failure(_answering(status))

    # Assert
    assert reason is TranscriptionFailure.STORAGE_UNAVAILABLE


def test_fetcher_reports_unreachable_storage_as_unavailable() -> None:
    # Arrange
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    # Act
    reason = _fetch_failure(handle)

    # Assert
    assert reason is TranscriptionFailure.STORAGE_UNAVAILABLE


def test_fetcher_refuses_an_expired_link_without_sending_a_request() -> None:
    # Arrange
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200)

    expired = AudioLink(url=_LINK.url, expires_at=_NOW)

    # Act
    with pytest.raises(TranscriptionError) as raised:
        _fetch(handle, link=expired)

    # Assert
    assert (raised.value.reason, requests) == (TranscriptionFailure.AUDIO_LINK_EXPIRED, [])


def test_fetcher_refuses_a_recording_declared_larger_than_the_limit() -> None:
    # Act
    reason = _fetch_failure(_answering(200, b"x" * 1_001), max_bytes=1_000)

    # Assert
    assert reason is TranscriptionFailure.AUDIO_TOO_LARGE


def test_fetcher_stops_a_recording_that_grows_past_the_limit_while_streaming() -> None:
    # Arrange
    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=iter([b"x" * 600, b"x" * 600]))

    # Act
    reason = _fetch_failure(handle, max_bytes=1_000)

    # Assert
    assert reason is TranscriptionFailure.AUDIO_TOO_LARGE


# --- Decoding ---


def test_decoder_turns_a_stereo_recording_into_mono_at_the_model_rate() -> None:
    # Act
    audio = _decode(_wav(_tone(2.0, 44_100)))

    # Assert
    assert (audio.samples.ndim, audio.duration_seconds) == (1, pytest.approx(2.0, abs=0.01))


def test_decoder_reads_a_flac_recording_to_its_end() -> None:
    # Act
    audio = _decode(_CLIP.read_bytes())

    # Assert
    assert audio.duration_seconds == pytest.approx(10.77, abs=0.01)


def test_decoder_reads_a_streamed_webm_recording_to_its_end() -> None:
    # Act
    audio = _decode(_LIVE_WEBM.read_bytes())

    # Assert
    assert audio.duration_seconds == pytest.approx(2.0, abs=0.05)


def test_decoder_scales_16_bit_samples_to_full_scale_floats() -> None:
    # Arrange
    tone = _tone(1.0, SAMPLE_RATE)

    # Act
    audio = _decode(_wav(tone, rate=SAMPLE_RATE, channels=1))

    # Assert
    assert np.allclose(audio.samples, tone / 32768, atol=1e-4)


def test_decoder_refuses_data_that_is_not_audio() -> None:
    # Act
    reason = _decode_failure(b"this is not a recording" * 100)

    # Assert
    assert reason is TranscriptionFailure.UNSUPPORTED_AUDIO


def test_decoder_refuses_a_recording_without_samples() -> None:
    # Act
    reason = _decode_failure(_wav(_tone(0.0, 44_100)))

    # Assert
    assert reason is TranscriptionFailure.UNSUPPORTED_AUDIO


def test_decoder_refuses_a_recording_longer_than_the_limit() -> None:
    # Act
    reason = _decode_failure(_wav(_tone(2.0, 44_100)), max_duration=timedelta(seconds=1))

    # Assert
    assert reason is TranscriptionFailure.AUDIO_TOO_LONG


def test_decoder_stops_a_recording_without_a_declared_duration_past_the_limit() -> None:
    # Act
    reason = _decode_failure(_LIVE_WEBM.read_bytes(), max_duration=timedelta(seconds=1))

    # Assert
    assert reason is TranscriptionFailure.AUDIO_TOO_LONG


# --- Loading ---


def test_loader_decodes_the_recording_it_fetched() -> None:
    # Arrange
    handler = _answering(200, _wav(_tone(1.0, 44_100)))

    # Act
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        loader = AudioLoader(
            AudioFetcher(client, max_bytes=10_000_000, now=lambda: _NOW),
            AudioDecoder(max_duration=_LIMIT),
        )
        audio = loader.load(_LINK)

    # Assert
    assert audio.duration_seconds == pytest.approx(1.0, abs=0.01)
