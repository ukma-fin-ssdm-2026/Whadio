from collections.abc import Sequence

from lingua import IsoCode639_1, LanguageDetector, LanguageDetectorBuilder


class TranscriptLanguage:
    """Names the language of a transcript from its text, unless the job names it."""

    def __init__(self, candidates: Sequence[str], *, fallback: str) -> None:
        codes = [IsoCode639_1.from_str(code) for code in candidates]
        self._detector: LanguageDetector = LanguageDetectorBuilder.from_iso_codes_639_1(
            *codes
        ).build()
        self._fallback: str = fallback

    def of(self, text: str, *, hint: str | None) -> str:
        if hint is not None:
            return hint
        language = self._detector.detect_language_of(text)
        return self._fallback if language is None else language.iso_code_639_1.name.lower()
