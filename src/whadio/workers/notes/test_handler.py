import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from ...contracts.common import Segment, Transcript
from ...contracts.notes import (
    ContextMeeting,
    MeetingBrief,
    NotesFailed,
    NotesFailure,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)
from .errors import NotesError
from .handler import NotesHandler, NotesResult
from .llm import Completion
from .prompt import ContextBudget, Prompt, PromptBuilder

_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)
_TRANSCRIPT = Transcript(
    language="uk",
    speakers=("Speaker 1",),
    segments=(
        Segment(start_seconds=0, end_seconds=2, speaker="Speaker 1", text="Беремо завантаження."),
    ),
)
_CONTEXT = ContextMeeting(
    meeting_id=uuid4(), name="Kickoff", recorded_at=_AT, transcript=_TRANSCRIPT
)
_JOB = NotesRequested(
    job_id=uuid4(),
    meeting_id=uuid4(),
    preset=NotesPreset.SUMMARY,
    meeting=MeetingBrief(name=None, recorded_at=_AT),
    transcript=_TRANSCRIPT,
    context=(_CONTEXT,),
    glossary=(),
)
_NOTES = """\
# Обсяг MVP

## Підсумок
Команда обрала завантаження файлів.

## Рішення
- Speaker 1: завантаження замість розширення.

## Завдання
—

## Відкриті питання
—
"""


class _Model:
    def __init__(self, answer: str | NotesError) -> None:
        self._answer: str | NotesError = answer

    @property
    def provider(self) -> NotesProvider:
        return NotesProvider.ANTHROPIC

    async def complete(self, prompt: Prompt) -> Completion:
        if isinstance(self._answer, NotesError):
            raise self._answer
        return Completion(text=self._answer, model_name=f"claude ({len(prompt.user)} chars)")


def _handle(answer: str | NotesError, budget: int = 100_000) -> NotesResult:
    builder = PromptBuilder(ContextBudget(max_input_tokens=budget, chars_per_token=3.0))
    return asyncio.run(NotesHandler(builder, _Model(answer), now=lambda: _AT).handle(_JOB))


def test_notes_take_the_proposed_name_from_the_model_answer() -> None:
    # Act
    result = _handle(_NOTES)

    # Assert
    assert isinstance(result, NotesReady)
    assert result.proposed_name == "Обсяг MVP"


def test_notes_record_the_context_meetings_they_were_written_with() -> None:
    # Act
    result = _handle(_NOTES)

    # Assert
    assert isinstance(result, NotesReady)
    assert result.context_meeting_ids == (_CONTEXT.meeting_id,)


def test_answer_without_the_preset_sections_fails_as_invalid_output() -> None:
    # Act
    result = _handle("# Обсяг MVP\n\n- без розділів.")

    # Assert
    assert result == NotesFailed(
        job_id=_JOB.job_id,
        meeting_id=_JOB.meeting_id,
        finished_at=_AT,
        reason=NotesFailure.INVALID_OUTPUT,
    )


def test_provider_failure_is_reported_with_its_reason() -> None:
    # Act
    result = _handle(NotesError(NotesFailure.PROVIDER_RATE_LIMITED))

    # Assert
    assert isinstance(result, NotesFailed)
    assert result.reason is NotesFailure.PROVIDER_RATE_LIMITED


def test_transcript_too_long_for_the_budget_fails_without_calling_the_model() -> None:
    # Act
    result = _handle(NotesError(NotesFailure.PROVIDER_UNAVAILABLE), budget=10)

    # Assert
    assert isinstance(result, NotesFailed)
    assert result.reason is NotesFailure.TRANSCRIPT_TOO_LONG
