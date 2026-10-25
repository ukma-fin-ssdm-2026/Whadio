import io
import time
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Final
from uuid import uuid4

import httpx2
import numpy as np
import pytest
from pydantic import Field, FilePath, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...contracts.transcription import AudioLink, TranscriptionRequested, TranscriptReady
from .audio import SAMPLE_RATE, AudioDecoder
from .diarization.device import DeviceUnavailableError, DiarizationDevice
from .pipeline import TranscriptionPipeline
from .settings import AsrSettings, load_asr_worker_settings
from .slot import build_pipeline

_TESTDATA = Path(__file__).parent / "testdata"
_NFR_002_BUDGET: Final = timedelta(minutes=15)
_HOUR_RECORDING_MINUTES: Final = (50, 60)


def _two_speakers() -> bytes:
    decoder = AudioDecoder(max_duration=timedelta(minutes=1))
    first, second = (
        decoder.decode(io.BytesIO((_TESTDATA / name).read_bytes())).samples
        for name in ("uk-bylyna.flac", "en-2277-149896-0032.flac")
    )
    joined = np.concatenate([first, np.zeros(SAMPLE_RATE, dtype=np.float32), second])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(SAMPLE_RATE)
        recording.writeframes((joined * 32767).astype(np.int16).tobytes())
    return buffer.getvalue()


def _pipeline_or_skip(settings: AsrSettings, client: httpx2.Client) -> TranscriptionPipeline:
    try:
        return build_pipeline(settings, client)
    except DeviceUnavailableError:
        pytest.skip("Diarization on cuda needs an NVIDIA GPU and torch from the cuda extra")


@pytest.mark.slow
@pytest.mark.models
@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_transcriber_tells_two_speakers_apart(
    monkeypatch: pytest.MonkeyPatch, device: DiarizationDevice
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_BROKER__URL", "amqp://unused:unused@localhost:5672/whadio")
    monkeypatch.setenv("WHADIO_ASR__DIARIZATION__DEVICE", device)
    settings = load_asr_worker_settings().asr
    recording = _two_speakers()
    job = TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(
            url=HttpUrl("http://storage.test/recordings/two-speakers.wav"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        language=None,
        glossary=(),
    )

    def serve(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=recording)

    # Act
    with httpx2.Client(transport=httpx2.MockTransport(serve)) as client:
        result = _pipeline_or_skip(settings, client).run(job)

    # Assert
    assert isinstance(result, TranscriptReady)
    assert result.transcript.speakers == ("Speaker 1", "Speaker 2")


# --- NFR-002: transcription time of a one-hour recording ---


class HourRecordingTestSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WHADIO_TEST_")

    hour_recording: FilePath | None = Field(
        default=None, description="A 50 to 60 minute recording for the NFR-002 timing test"
    )


@dataclass(frozen=True, slots=True)
class HourRecording:
    pipeline: TranscriptionPipeline
    job: TranscriptionRequested


@pytest.fixture(scope="module")
def hour_recording() -> Iterator[HourRecording]:
    path = HourRecordingTestSettings().hour_recording
    if path is None:
        pytest.skip("Set WHADIO_TEST_HOUR_RECORDING to a 50 to 60 minute recording")
    recording = path.read_bytes()
    decoder = AudioDecoder(max_duration=timedelta(minutes=_HOUR_RECORDING_MINUTES[1]))
    minutes = decoder.decode(io.BytesIO(recording)).duration_seconds / 60
    if not _HOUR_RECORDING_MINUTES[0] <= minutes <= _HOUR_RECORDING_MINUTES[1]:
        pytest.fail(f"WHADIO_TEST_HOUR_RECORDING lasts {minutes:.1f} min, not 50 to 60")
    job = TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(
            url=HttpUrl("http://storage.test/recordings/hour.audio"),
            expires_at=datetime.now(UTC) + timedelta(hours=3),
        ),
        language=None,
        glossary=(),
    )

    def serve(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=recording)

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WHADIO_BROKER__URL", "amqp://unused:unused@localhost:5672/whadio")
        settings = load_asr_worker_settings().asr
    with httpx2.Client(transport=httpx2.MockTransport(serve)) as client:
        # The models load here, in setup, so the test's call phase times only the transcription.
        yield HourRecording(build_pipeline(settings, client), job)


@pytest.mark.slow
@pytest.mark.models
@pytest.mark.parametrize("run", [1, 2, 3])
def test_hour_recording_is_transcribed_within_the_nfr_002_budget(
    hour_recording: HourRecording, run: int
) -> None:
    # Arrange
    del run
    start = time.perf_counter()

    # Act
    result = hour_recording.pipeline.run(hour_recording.job)
    elapsed = timedelta(seconds=time.perf_counter() - start)

    # Assert
    assert (isinstance(result, TranscriptReady), elapsed <= _NFR_002_BUDGET) == (True, True)
