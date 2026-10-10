"""The composition root of a slot's child process.

The worker's main process imports this module to hand `build_transcriber` to its slots, so the
model libraries are imported only inside the functions, in the child that uses them.
"""

from collections.abc import Callable

import httpx2

from ...contracts.transcription import TranscriptionRequested
from ...shared.logs import LogLevel, configure_logging
from .audio import AudioDecoder, AudioFetcher, AudioLoader
from .diarization import IDiarizer
from .language import TranscriptLanguage
from .pipeline import TranscriptionPipeline, TranscriptionResult
from .recognition import ISpeechRecognizer, RecognizerKind
from .settings import AsrSettings, DiarizationSettings


def build_transcriber(
    settings: AsrSettings, log_level: LogLevel
) -> Callable[[TranscriptionRequested], TranscriptionResult]:
    configure_logging(log_level)
    client = httpx2.Client(timeout=settings.fetch_timeout.total_seconds())
    return build_pipeline(settings, client).run


def build_pipeline(settings: AsrSettings, client: httpx2.Client) -> TranscriptionPipeline:
    return TranscriptionPipeline(
        audio=AudioLoader(
            AudioFetcher(client, max_bytes=settings.max_audio_bytes),
            AudioDecoder(max_duration=settings.max_duration),
        ),
        diarizer=_load_diarizer(settings.diarization),
        recognizer=_load_recognizer(settings),
        language=TranscriptLanguage(settings.languages, fallback=settings.fallback_language),
    )


def _load_diarizer(settings: DiarizationSettings) -> IDiarizer:
    from .diarization.pyannote import load_pyannote

    token = None if settings.hf_token is None else settings.hf_token.get_secret_value()
    return load_pyannote(
        settings.model, token=token, embedding_batch_size=settings.embedding_batch_size
    )


def _load_recognizer(settings: AsrSettings) -> ISpeechRecognizer:
    match settings.recognizer:
        case RecognizerKind.PARAKEET:
            from .recognition.parakeet import load_parakeet

            return load_parakeet(
                settings.parakeet.model, quantization=settings.parakeet.quantization
            )
        case RecognizerKind.WHISPER:
            from .recognition.whisper import load_whisper

            return load_whisper(
                settings.whisper.model,
                compute_type=settings.whisper.compute_type,
                beam_size=settings.whisper.beam_size,
            )
