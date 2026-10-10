from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from pydantic import HttpUrl

from ...contracts.common import GlossaryEntry, Segment, Transcript
from ...contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from ..supervision.jobs import RunFailure
from .audio import Audio, AudioDecoder, AudioFetcher, AudioLoader
from .diarization import SpeakerTurn
from .language import TranscriptLanguage
from .pipeline import TranscriptionPipeline, TranscriptionResult, transcription_failure
from .recognition import RecognitionHints, RecognizedSegment, Word

type _Handler = Callable[[httpx2.Request], httpx2.Response]

_NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
_CLIP = (Path(__file__).parent / "testdata" / "en-2277-149896-0032.flac").read_bytes()
_GLOSSARY = (GlossaryEntry(term="ваді", preferred_form="Whadio", description="The product"),)
_TURNS = (
    SpeakerTurn(start=0.0, end=4.0, speaker="SPEAKER_01"),
    SpeakerTurn(start=4.0, end=10.0, speaker="SPEAKER_00"),
)
_RECOGNIZED = (
    RecognizedSegment(
        start=0.5,
        end=8.0,
        text="By the time he reached his own street he was keenly alive",
        words=(
            Word(start=0.5, end=1.5, text=" By the time"),
            Word(start=1.5, end=3.5, text=" he reached his own street"),
            Word(start=4.5, end=8.0, text=" he was keenly alive"),
        ),
    ),
)


class _Diarizer:
    def diarize(self, audio: Audio) -> tuple[SpeakerTurn, ...]:
        del audio
        return _TURNS


class _Recognizer:
    def __init__(self) -> None:
        self.hints: list[RecognitionHints] = []

    @property
    def model_name(self) -> str:
        return "fake-asr"

    def recognize(self, audio: Audio, hints: RecognitionHints) -> tuple[RecognizedSegment, ...]:
        del audio
        self.hints.append(hints)
        return _RECOGNIZED


def _serving(status: int, content: bytes) -> _Handler:
    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=content)

    return handle


def _job(language: str | None = None) -> TranscriptionRequested:
    return TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(
            url=HttpUrl("http://storage.test/recordings/m.flac?X-Amz-Signature=abc"),
            expires_at=_NOW + timedelta(minutes=10),
        ),
        language=language,
        glossary=_GLOSSARY,
    )


def _run(
    job: TranscriptionRequested,
    handler: _Handler | None = None,
    recognizer: _Recognizer | None = None,
) -> TranscriptionResult:
    transport = httpx2.MockTransport(handler or _serving(200, _CLIP))
    with httpx2.Client(transport=transport) as client:
        pipeline = TranscriptionPipeline(
            audio=AudioLoader(
                AudioFetcher(client, max_bytes=10_000_000, now=lambda: _NOW),
                AudioDecoder(max_duration=timedelta(minutes=10)),
            ),
            diarizer=_Diarizer(),
            recognizer=recognizer or _Recognizer(),
            language=TranscriptLanguage(("uk", "en", "ru"), fallback="uk"),
            now=lambda: _NOW,
        )
        return pipeline.run(job)


def _transcript_of(result: TranscriptionResult) -> Transcript:
    assert isinstance(result, TranscriptReady)
    return result.transcript


def test_transcript_is_split_by_speaker_in_the_detected_language() -> None:
    # Act
    result = _run(_job())

    # Assert
    assert _transcript_of(result) == Transcript(
        language="en",
        speakers=("Speaker 1", "Speaker 2"),
        segments=(
            Segment(
                start_seconds=0.5,
                end_seconds=3.5,
                speaker="Speaker 1",
                text="By the time he reached his own street",
            ),
            Segment(
                start_seconds=4.5, end_seconds=8.0, speaker="Speaker 2", text="he was keenly alive"
            ),
        ),
    )


def test_language_the_job_names_is_kept_over_the_detected_one() -> None:
    # Act
    result = _run(_job(language="uk"))

    # Assert
    assert _transcript_of(result).language == "uk"


def test_recognizer_gets_the_job_language_and_glossary() -> None:
    # Arrange
    recognizer = _Recognizer()

    # Act
    _run(_job(language="uk"), recognizer=recognizer)

    # Assert
    assert recognizer.hints == [RecognitionHints(language="uk", glossary=_GLOSSARY)]


def test_ready_transcript_reports_the_recording_duration() -> None:
    # Act
    result = _run(_job())

    # Assert
    assert isinstance(result, TranscriptReady)
    assert result.duration_seconds == pytest.approx(10.77, abs=0.01)


def test_ready_transcript_names_the_recognition_model() -> None:
    # Act
    result = _run(_job())

    # Assert
    assert isinstance(result, TranscriptReady)
    assert result.model_name == "fake-asr"


def test_missing_recording_fails_the_job_with_its_reason() -> None:
    # Arrange
    job = _job()

    # Act
    result = _run(job, handler=_serving(404, b""))

    # Assert
    assert result == TranscriptionFailed(
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        finished_at=_NOW,
        reason=TranscriptionFailure.AUDIO_NOT_FOUND,
    )


def test_file_that_is_not_audio_fails_the_job_as_unsupported() -> None:
    # Act
    result = _run(_job(), handler=_serving(200, b"not a recording" * 100))

    # Assert
    assert isinstance(result, TranscriptionFailed)
    assert result.reason is TranscriptionFailure.UNSUPPORTED_AUDIO


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (RunFailure.CRASHED, TranscriptionFailure.WORKER_CRASHED),
        (RunFailure.TIMED_OUT, TranscriptionFailure.TIMED_OUT),
        (RunFailure.ERRORED, TranscriptionFailure.INTERNAL_ERROR),
    ],
)
def test_run_failure_maps_to_a_transcription_failure(
    failure: RunFailure, expected: TranscriptionFailure
) -> None:
    # Act
    result = transcription_failure(_job(), failure)

    # Assert
    assert isinstance(result, TranscriptionFailed)
    assert result.reason is expected
