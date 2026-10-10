import io
from datetime import timedelta
from pathlib import Path

import pytest

from ..audio import Audio, AudioDecoder
from . import RecognitionHints, RecognizedSegment, Word
from .parakeet import ParakeetRecognizer, load_parakeet, words_from_tokens

_CLIP = Path(__file__).parents[1] / "testdata" / "en-2277-149896-0032.flac"


def test_tokens_are_joined_into_words_at_their_leading_spaces() -> None:
    # Act
    words = words_from_tokens(
        [" note", "book", ",", " pen"], [0.0, 0.25, 0.5, 0.75], start=10.0, end=11.5
    )

    # Assert
    assert words == (
        Word(start=10.0, end=10.75, text=" notebook,"),
        Word(start=10.75, end=11.5, text=" pen"),
    )


def test_blank_token_separates_the_words_around_it() -> None:
    # Act
    words = words_from_tokens([" Hi", " ", "there"], [0.0, 0.25, 0.5], start=0.0, end=1.0)

    # Assert
    assert [word.text for word in words] == [" Hi", " there"]


def test_segment_without_tokens_has_no_words() -> None:
    # Act
    words = words_from_tokens([], [], start=0.0, end=1.0)

    # Assert
    assert words == ()


@pytest.fixture(scope="module")
def parakeet() -> ParakeetRecognizer:
    return load_parakeet("nemo-parakeet-tdt-0.6b-v3", quantization="int8")


@pytest.fixture(scope="module")
def clip() -> Audio:
    return AudioDecoder(max_duration=timedelta(minutes=1)).decode(io.BytesIO(_CLIP.read_bytes()))


@pytest.fixture(scope="module")
def recognized(parakeet: ParakeetRecognizer, clip: Audio) -> tuple[RecognizedSegment, ...]:
    return parakeet.recognize(clip, RecognitionHints(language=None, glossary=()))


@pytest.mark.slow
@pytest.mark.models
def test_parakeet_recognizes_english_speech(recognized: tuple[RecognizedSegment, ...]) -> None:
    # Act
    text = " ".join(segment.text for segment in recognized).lower()

    # Assert
    assert "keenly alive to the difficulties" in text


@pytest.mark.slow
@pytest.mark.models
def test_parakeet_words_lie_within_the_recording(
    recognized: tuple[RecognizedSegment, ...], clip: Audio
) -> None:
    # Act
    words = [word for segment in recognized for word in segment.words]

    # Assert
    assert 0 <= min(w.start for w in words) <= max(w.end for w in words) <= clip.duration_seconds
