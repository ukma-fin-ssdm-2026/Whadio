from collections.abc import Sequence
from typing import Final

import onnx_asr
from onnx_asr.adapters import TimestampedSegmentResultsAsrAdapter
from onnx_asr.vad import TimestampedSegmentResult

from ..audio import SAMPLE_RATE, Audio
from . import RecognitionHints, RecognizedSegment, Word

_CPU: Final = ("CPUExecutionProvider",)


class ParakeetRecognizer:
    def __init__(self, model: TimestampedSegmentResultsAsrAdapter, model_name: str) -> None:
        self._model: TimestampedSegmentResultsAsrAdapter = model
        self._model_name: str = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def recognize(self, audio: Audio, hints: RecognitionHints) -> tuple[RecognizedSegment, ...]:
        # Parakeet takes no hints: it detects the language itself, and it has no way to bias
        # recognition towards the glossary (FR-029 holds only with Whisper).
        del hints
        results = self._model.recognize(audio.samples, sample_rate=SAMPLE_RATE)
        return tuple(_segment(result) for result in results)


def load_parakeet(model: str, *, quantization: str | None) -> ParakeetRecognizer:
    asr = onnx_asr.load_model(model, quantization=quantization, providers=_CPU)
    vad = onnx_asr.load_vad("silero", providers=_CPU)
    name = model if quantization is None else f"{model} ({quantization})"
    return ParakeetRecognizer(asr.with_vad(vad).with_timestamps(), name)


def words_from_tokens(
    tokens: Sequence[str], offsets: Sequence[float], *, start: float, end: float
) -> tuple[Word, ...]:
    """Join sub-word tokens into words; `offsets` are token starts relative to `start`.

    Adapted from local-asr `src/transcribe.py` (06ec281), which kept every token as a word.
    """
    firsts: list[int] = []
    texts: list[str] = []
    space = False
    for index, token in enumerate(tokens):
        if not token.strip():
            space = True
            continue
        piece = f" {token}" if space and not token.startswith(" ") else token
        space = False
        if texts and not piece.startswith(" "):
            texts[-1] += piece
        else:
            firsts.append(index)
            texts.append(piece)
    if not firsts:
        return ()
    ends = [start + offsets[first] for first in firsts[1:]] + [end]
    return tuple(
        Word(start=start + offsets[first], end=word_end, text=text)
        for first, word_end, text in zip(firsts, ends, texts, strict=True)
    )


def _segment(result: TimestampedSegmentResult) -> RecognizedSegment:
    words = (
        words_from_tokens(result.tokens, result.timestamps, start=result.start, end=result.end)
        if result.tokens is not None and result.timestamps is not None
        else ()
    )
    return RecognizedSegment(start=result.start, end=result.end, text=result.text, words=words)
