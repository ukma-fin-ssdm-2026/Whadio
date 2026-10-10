import io
from datetime import timedelta
from pathlib import Path

import pytest
from faster_whisper.transcribe import Segment as WhisperSegment
from faster_whisper.transcribe import Word as WhisperWord

from ....contracts.common import GlossaryEntry
from ..audio import AudioDecoder
from . import RecognitionHints, RecognizedSegment, Word
from .whisper import hotwords, load_whisper, recognized_segment

_CLIP = Path(__file__).parents[1] / "testdata" / "en-2277-149896-0032.flac"


def _whisper_segment(words: list[WhisperWord] | None) -> WhisperSegment:
    return WhisperSegment(
        id=1,
        seek=0,
        start=1.0,
        end=2.0,
        text=" Hello there",
        tokens=[],
        avg_logprob=-0.2,
        compression_ratio=1.1,
        no_speech_prob=0.01,
        words=words,
        temperature=0.0,
    )


def test_hotwords_list_the_preferred_forms_of_the_glossary() -> None:
    # Arrange
    glossary = (
        GlossaryEntry(term="ваді", preferred_form="Whadio", description=""),
        GlossaryEntry(term="кубер", preferred_form="Kubernetes", description="Orchestrator"),
    )

    # Act
    words = hotwords(glossary)

    # Assert
    assert words == "Whadio, Kubernetes"


def test_empty_glossary_gives_no_hotwords() -> None:
    # Act
    words = hotwords(())

    # Assert
    assert words is None


def test_whisper_segment_keeps_its_word_timings() -> None:
    # Arrange
    segment = _whisper_segment(
        [
            WhisperWord(start=1.0, end=1.5, word=" Hello", probability=0.9),
            WhisperWord(start=1.5, end=2.0, word=" there", probability=0.8),
        ]
    )

    # Act
    recognized = recognized_segment(segment)

    # Assert
    assert recognized == RecognizedSegment(
        start=1.0,
        end=2.0,
        text=" Hello there",
        words=(Word(start=1.0, end=1.5, text=" Hello"), Word(start=1.5, end=2.0, text=" there")),
    )


def test_whisper_segment_without_word_timings_has_no_words() -> None:
    # Act
    recognized = recognized_segment(_whisper_segment(None))

    # Assert
    assert recognized.words == ()


@pytest.mark.slow
@pytest.mark.models
def test_whisper_recognizes_english_speech() -> None:
    # Arrange
    whisper = load_whisper("base", compute_type="int8", beam_size=5)
    audio = AudioDecoder(max_duration=timedelta(minutes=1)).decode(io.BytesIO(_CLIP.read_bytes()))

    # Act
    recognized = whisper.recognize(audio, RecognitionHints(language="en", glossary=()))

    # Assert
    text = " ".join(segment.text for segment in recognized).lower()
    assert "keenly alive to the difficulties" in text
