import asyncio
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

import pytest

from ...contracts.common import GlossaryEntry, Segment, Transcript
from ...contracts.notes import (
    ContextMeeting,
    MeetingBrief,
    NotesFailure,
    NotesPreset,
    NotesRequested,
)
from .errors import NotesError
from .fakes import ScriptedAnswer, ScriptedChatModel
from .llm import Completion
from .map_reduce import MapReducePrompts
from .prompt import ContextBudget, PromptBuilder
from .writer import NotesWriter, WrittenNotes

_AT: Final = datetime(2026, 10, 9, 18, tzinfo=UTC)
_NOTES: Final = """\
# Обсяг MVP

## Підсумок
Команда обрала завантаження файлів.

## Рішення
—

## Завдання
—

## Відкриті питання
—
"""
_PARTIAL: Final = "- [00:00:00] Обговорили обсяг."
# The extract instructions take about 1,450 characters and each segment about 1,020, so this
# budget fits two segments in a part, the five-segment meeting below in three parts, and their
# partial notes, the glossary and the context meeting in the reduce prompt; one notes prompt for
# the whole meeting would take over 7,000.
_BUDGET: Final = ContextBudget(max_input_tokens=4_000, chars_per_token=1.0)
_GENEROUS: Final = ContextBudget(max_input_tokens=100_000, chars_per_token=1.0)


def _transcript(*texts: str) -> Transcript:
    return Transcript(
        language="uk",
        speakers=("Speaker 1",),
        segments=tuple(
            Segment(start_seconds=second, end_seconds=second + 1, speaker="Speaker 1", text=text)
            for second, text in enumerate(texts)
        ),
    )


_LONG: Final = _transcript(*(letter * 1_000 for letter in "abcde"))
_CONTEXT: Final = ContextMeeting(
    meeting_id=uuid4(),
    name="Kickoff",
    recorded_at=datetime(2026, 10, 2, 16, tzinfo=UTC),
    transcript=_transcript("Обговорили реліз."),
)
_GLOSSARY: Final = (GlossaryEntry(term="віспер", preferred_form="Whisper", description=""),)


def _request(
    transcript: Transcript = _LONG, context: tuple[ContextMeeting, ...] = (_CONTEXT,)
) -> NotesRequested:
    return NotesRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        preset=NotesPreset.SUMMARY,
        meeting=MeetingBrief(name=None, recorded_at=_AT),
        transcript=transcript,
        context=context,
        glossary=_GLOSSARY,
    )


def _write(
    model: ScriptedChatModel, request: NotesRequested, budget: ContextBudget = _BUDGET
) -> WrittenNotes:
    builder = PromptBuilder(budget)
    writer = NotesWriter(builder, MapReducePrompts(builder, budget), model)
    return asyncio.run(writer.write(request))


def _three_parts(*reduce: ScriptedAnswer) -> ScriptedChatModel:
    return ScriptedChatModel(_PARTIAL, _PARTIAL, _PARTIAL, *reduce)


def _single_pass_chars(request: NotesRequested) -> int:
    prompt = PromptBuilder(_GENEROUS).build(request)
    return len(prompt.system) + len(prompt.user)


def test_notes_that_fit_one_prompt_are_written_in_one_call() -> None:
    # Arrange
    request = _request(_transcript("Беремо завантаження."))
    model = ScriptedChatModel(_NOTES)

    # Act
    _write(model, request)

    # Assert
    assert model.prompts == [PromptBuilder(_BUDGET).build(request)]


def test_transcript_that_exactly_fits_one_prompt_is_written_in_one_call() -> None:
    # Arrange
    request = _request(context=())
    budget = ContextBudget(max_input_tokens=_single_pass_chars(request), chars_per_token=1.0)
    model = ScriptedChatModel(_NOTES)

    # Act
    _write(model, request, budget)

    # Assert
    assert len(model.prompts) == 1


def test_transcript_one_char_over_one_prompt_is_written_by_map_reduce() -> None:
    # Arrange
    request = _request(context=())
    budget = ContextBudget(max_input_tokens=_single_pass_chars(request) - 1, chars_per_token=1.0)
    model = ScriptedChatModel(_PARTIAL, _NOTES)

    # Act
    _write(model, request, budget)

    # Assert
    assert len(model.prompts) == 2


def test_map_reduce_extracts_each_part_before_the_reduce_call() -> None:
    # Arrange
    model = _three_parts(_NOTES)

    # Act
    _write(model, _request())

    # Assert
    assert [prompt.user.startswith("<transcript_part>") for prompt in model.prompts] == [
        True,
        True,
        True,
        False,
    ]


def test_map_reduce_reports_its_number_of_parts() -> None:
    # Act
    written = _write(_three_parts(_NOTES), _request())

    # Assert
    assert written.transcript_parts == 3


def test_glossary_goes_only_into_the_reduce_prompt() -> None:
    # Arrange
    model = _three_parts(_NOTES)

    # Act
    _write(model, _request())

    # Assert
    assert ["<glossary>" in prompt.user for prompt in model.prompts] == [False, False, False, True]


def test_context_meetings_go_only_into_the_reduce_prompt() -> None:
    # Arrange
    model = _three_parts(_NOTES)

    # Act
    _write(model, _request())

    # Assert
    assert ["<context_meeting" in prompt.user for prompt in model.prompts] == [
        False,
        False,
        False,
        True,
    ]


def test_map_reduce_notes_record_the_context_meetings_of_the_reduce_prompt() -> None:
    # Act
    written = _write(_three_parts(_NOTES), _request())

    # Assert
    assert written.context_meeting_ids == (_CONTEXT.meeting_id,)


def test_reduce_prompt_holds_each_partial_note_in_a_partial_notes_element() -> None:
    # Arrange
    model = ScriptedChatModel(
        "- [00:00:00] Перша.", "- [00:00:02] Друга.", "- [00:00:04] Третя.", _NOTES
    )

    # Act
    _write(model, _request())

    # Assert
    assert (
        '<partial_notes part="1">\n- [00:00:00] Перша.\n</partial_notes>\n'
        '<partial_notes part="2">\n- [00:00:02] Друга.\n</partial_notes>\n'
        '<partial_notes part="3">\n- [00:00:04] Третя.\n</partial_notes>'
    ) in model.prompts[-1].user


def test_map_reduce_notes_report_the_model_of_the_reduce_call() -> None:
    # Arrange
    extract = Completion(text=_PARTIAL, model_name="extract-model")
    model = ScriptedChatModel(
        extract, extract, extract, Completion(text=_NOTES, model_name="reduce-model")
    )

    # Act
    written = _write(model, _request())

    # Assert
    assert written.model_name == "reduce-model"


def test_map_reduce_notes_take_the_name_from_the_reduce_answer() -> None:
    # Act
    written = _write(_three_parts(_NOTES), _request())

    # Assert
    assert written.notes.proposed_name == "Обсяг MVP"


def test_partial_notes_too_long_for_the_reduce_prompt_fail_as_too_long() -> None:
    # Arrange
    long_partial = "- " + "x" * 1_000
    model = ScriptedChatModel(long_partial, long_partial, long_partial)

    # Act / Assert
    with pytest.raises(NotesError) as raised:
        _write(model, _request())
    assert raised.value.reason is NotesFailure.TRANSCRIPT_TOO_LONG


def test_segment_too_long_for_a_part_fails_as_too_long() -> None:
    # Arrange
    request = _request(_transcript("x" * 3_000))

    # Act / Assert
    with pytest.raises(NotesError) as raised:
        _write(ScriptedChatModel(), request)
    assert raised.value.reason is NotesFailure.TRANSCRIPT_TOO_LONG


def test_segment_too_long_for_a_part_fails_without_calling_the_model() -> None:
    # Arrange
    model = ScriptedChatModel()

    # Act
    with pytest.raises(NotesError):
        _write(model, _request(_transcript("x" * 3_000)))

    # Assert
    assert model.prompts == []


def test_failed_extract_call_fails_with_its_reason() -> None:
    # Arrange
    model = ScriptedChatModel(_PARTIAL, NotesError(NotesFailure.PROVIDER_UNAVAILABLE))

    # Act / Assert
    with pytest.raises(NotesError) as raised:
        _write(model, _request())
    assert raised.value.reason is NotesFailure.PROVIDER_UNAVAILABLE


def test_failed_reduce_call_fails_with_its_reason() -> None:
    # Arrange
    model = _three_parts(NotesError(NotesFailure.PROVIDER_REFUSED))

    # Act / Assert
    with pytest.raises(NotesError) as raised:
        _write(model, _request())
    assert raised.value.reason is NotesFailure.PROVIDER_REFUSED


def test_reduce_answer_without_the_preset_sections_fails_as_invalid_output() -> None:
    # Arrange
    model = _three_parts("# Обсяг MVP\n\n- без розділів.")

    # Act / Assert
    with pytest.raises(NotesError) as raised:
        _write(model, _request())
    assert raised.value.reason is NotesFailure.INVALID_OUTPUT
