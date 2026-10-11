import pytest

from .language import TranscriptLanguage

_UKRAINIAN = (
    "Кущику! Билина каже. Я на чужині. Хто щиро поважа родину, свій рідний край, тому не всюди "
    "рай: чужина в'ялить, як билину."
)
_RUSSIAN = "Давайте обсудим релиз на следующей неделе и решим, кто берёт проверку кода."
_ENGLISH = (
    "By the time he reached his own street he was keenly alive to the difficulties of his "
    "situation."
)


@pytest.fixture(scope="module")
def language() -> TranscriptLanguage:
    return TranscriptLanguage(("uk", "en", "ru", "pl"), fallback="uk")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(_UKRAINIAN, "uk", id="uk"),
        pytest.param(_RUSSIAN, "ru", id="ru"),
        pytest.param(_ENGLISH, "en", id="en"),
    ],
)
def test_language_is_detected_from_the_transcript_text(
    language: TranscriptLanguage, text: str, expected: str
) -> None:
    # Act
    detected = language.of(text, hint=None)

    # Assert
    assert detected == expected


def test_language_the_job_names_wins_over_the_text(language: TranscriptLanguage) -> None:
    # Act
    chosen = language.of(_ENGLISH, hint="uk")

    # Assert
    assert chosen == "uk"


def test_transcript_without_words_takes_the_fallback_language() -> None:
    # Arrange
    language = TranscriptLanguage(("en", "pl"), fallback="uk")

    # Act
    chosen = language.of("", hint=None)

    # Assert
    assert chosen == "uk"


def test_unknown_candidate_language_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="enum member"):
        TranscriptLanguage(("uk", "xx"), fallback="uk")
