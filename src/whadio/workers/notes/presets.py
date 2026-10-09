from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ...contracts.notes import NotesPreset

FALLBACK_LANGUAGE: Final = "en"


@dataclass(frozen=True, slots=True)
class Section:
    headings: Mapping[str, str]
    instruction: str

    def heading(self, language: str) -> str:
        return self.headings.get(language, self.headings[FALLBACK_LANGUAGE])


@dataclass(frozen=True, slots=True)
class PresetSpec:
    purpose: str
    sections: tuple[Section, ...]

    def headings(self, language: str) -> tuple[str, ...]:
        return tuple(section.heading(language) for section in self.sections)


def _headings(en: str, uk: str) -> Mapping[str, str]:
    return MappingProxyType({"en": en, "uk": uk})


_DECISIONS: Final = Section(
    _headings("Decisions", "Рішення"),
    "A bulleted list of what was decided, each with who decided or proposed it.",
)
_ACTION_ITEMS: Final = Section(
    _headings("Action items", "Завдання"),
    "A bulleted list in the form `owner — task — deadline`; leave the deadline out when none "
    "was stated.",
)
_OPEN_QUESTIONS: Final = Section(
    _headings("Open questions", "Відкриті питання"),
    "A bulleted list of questions raised and left unresolved.",
)

PRESETS: Final[Mapping[NotesPreset, PresetSpec]] = MappingProxyType(
    {
        NotesPreset.SUMMARY: PresetSpec(
            purpose="a short summary that a member who missed the meeting reads in two minutes",
            sections=(
                Section(
                    _headings("Summary", "Підсумок"),
                    "Three to six sentences: what the meeting was about and how it ended.",
                ),
                _DECISIONS,
                _ACTION_ITEMS,
                _OPEN_QUESTIONS,
            ),
        ),
        NotesPreset.DETAILED: PresetSpec(
            purpose="a detailed write-up that a member who missed the meeting can rely on "
            "instead of the recording",
            sections=(
                Section(
                    _headings("Overview", "Огляд"),
                    "Who took part, what the meeting was for and what it achieved.",
                ),
                Section(
                    _headings("Discussion", "Обговорення"),
                    "One `###` subsection per topic, in the order discussed, keeping the "
                    "arguments, numbers, names and conclusions.",
                ),
                _DECISIONS,
                _ACTION_ITEMS,
                _OPEN_QUESTIONS,
            ),
        ),
        NotesPreset.INTERVIEW: PresetSpec(
            purpose="notes of an interview, where one person mostly asks and another mostly "
            "answers",
            sections=(
                Section(
                    _headings("Participants and context", "Учасники та контекст"),
                    "Who interviewed whom and what the interview was for.",
                ),
                Section(
                    _headings("Questions and answers", "Запитання та відповіді"),
                    "Each question as a bold line, followed by a faithful summary of its answer.",
                ),
                Section(
                    _headings("Key findings", "Ключові висновки"),
                    "A bulleted list of the most important facts and insights from the answers.",
                ),
                Section(
                    _headings("Follow-ups", "Подальші кроки"),
                    "A bulleted list of what to check, ask or do next.",
                ),
            ),
        ),
    }
)
