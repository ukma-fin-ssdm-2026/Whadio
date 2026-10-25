import io
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx2
import numpy as np
import pytest
from pydantic import HttpUrl

from ...contracts.transcription import AudioLink, TranscriptionRequested, TranscriptReady
from .audio import SAMPLE_RATE, AudioDecoder
from .diarization.device import DeviceUnavailableError, DiarizationDevice
from .pipeline import TranscriptionPipeline
from .settings import AsrSettings, load_asr_worker_settings
from .slot import build_pipeline

_TESTDATA = Path(__file__).parent / "testdata"


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
