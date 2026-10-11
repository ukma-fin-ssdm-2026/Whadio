import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from ...contracts.common import Transcript
from ...contracts.transcription import (
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from ..supervision.jobs import RunFailure
from .audio import AudioLoader
from .diarization import IDiarizer
from .errors import TranscriptionError
from .language import TranscriptLanguage
from .recognition import ISpeechRecognizer, RecognitionHints
from .speakers import attribute_speakers

logger = logging.getLogger(__name__)

type TranscriptionResult = TranscriptReady | TranscriptionFailed

_RUN_FAILURES: Final = {
    RunFailure.CRASHED: TranscriptionFailure.WORKER_CRASHED,
    RunFailure.TIMED_OUT: TranscriptionFailure.TIMED_OUT,
    RunFailure.ERRORED: TranscriptionFailure.INTERNAL_ERROR,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def transcription_failure(job: TranscriptionRequested, failure: RunFailure) -> TranscriptionResult:
    return TranscriptionFailed(
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        finished_at=_utc_now(),
        reason=_RUN_FAILURES[failure],
    )


class TranscriptionPipeline:
    def __init__(
        self,
        *,
        audio: AudioLoader,
        diarizer: IDiarizer,
        recognizer: ISpeechRecognizer,
        language: TranscriptLanguage,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._audio: AudioLoader = audio
        self._diarizer: IDiarizer = diarizer
        self._recognizer: ISpeechRecognizer = recognizer
        self._language: TranscriptLanguage = language
        self._now: Callable[[], datetime] = now

    def run(self, job: TranscriptionRequested) -> TranscriptionResult:
        try:
            audio = self._audio.load(job.audio)
            turns = self._diarizer.diarize(audio)
            recognized = self._recognizer.recognize(
                audio, RecognitionHints(language=job.language, glossary=job.glossary)
            )
        except TranscriptionError as error:
            logger.warning("Transcription of job %s failed: %s", job.job_id, error.reason)
            return TranscriptionFailed(
                job_id=job.job_id,
                meeting_id=job.meeting_id,
                finished_at=self._now(),
                reason=error.reason,
            )
        attribution = attribute_speakers(turns, recognized)
        text = "\n".join(segment.text for segment in attribution.segments)
        language = self._language.of(text, hint=job.language)
        logger.info(
            "Transcribed job %s: %.0f s of audio, %d speakers, %d segments",
            job.job_id,
            audio.duration_seconds,
            len(attribution.speakers),
            len(attribution.segments),
        )
        return TranscriptReady(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            finished_at=self._now(),
            model_name=self._recognizer.model_name,
            duration_seconds=audio.duration_seconds,
            transcript=Transcript(
                language=language,
                speakers=attribution.speakers,
                segments=attribution.segments,
            ),
        )
