from collections.abc import Sequence
from typing import Final

from faster_whisper import WhisperModel
from faster_whisper.transcribe import Segment

from ....contracts.common import GlossaryEntry
from ..audio import Audio
from . import RecognitionHints, RecognizedSegment, Word

_VAD_PARAMETERS: Final = {"min_silence_duration_ms": 500}


class WhisperRecognizer:
    def __init__(self, model: WhisperModel, model_name: str, *, beam_size: int) -> None:
        self._model: WhisperModel = model
        self._model_name: str = model_name
        self._beam_size: int = beam_size

    @property
    def model_name(self) -> str:
        return self._model_name

    def recognize(self, audio: Audio, hints: RecognitionHints) -> tuple[RecognizedSegment, ...]:
        segments, _ = self._model.transcribe(
            audio.samples,
            language=hints.language,
            beam_size=self._beam_size,
            word_timestamps=True,
            # With the previous text as context, or without VAD on long silences, Whisper falls into
            # repeating one sentence for the rest of the recording.
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=_VAD_PARAMETERS,
            hotwords=hotwords(hints.glossary),
        )
        return tuple(recognized_segment(segment) for segment in segments)


def load_whisper(model: str, *, compute_type: str, beam_size: int) -> WhisperRecognizer:
    # No `download_root`: faster-whisper 1.2.1 then passes `local_dir_use_symlinks`, which
    # huggingface-hub 2 rejects. Models go to the Hugging Face cache instead.
    whisper = WhisperModel(model, device="cpu", compute_type=compute_type)
    return WhisperRecognizer(
        whisper, f"faster-whisper {model} ({compute_type})", beam_size=beam_size
    )


def hotwords(glossary: Sequence[GlossaryEntry]) -> str | None:
    return ", ".join(entry.preferred_form for entry in glossary) or None


def recognized_segment(segment: Segment) -> RecognizedSegment:
    words = tuple(
        Word(start=word.start, end=word.end, text=word.word) for word in segment.words or ()
    )
    return RecognizedSegment(start=segment.start, end=segment.end, text=segment.text, words=words)
