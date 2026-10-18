import pytest

from ...contracts.notes import NotesFailure
from .errors import NotesError
from .output import parse_notes

_HEADINGS = ("Підсумок", "Рішення")
_NOTES = """\
# Планування MVP

## Підсумок
Команда погодила обсяг MVP.

## Рішення
- Завантаження відео замість розширення.
"""


def test_parsed_notes_take_their_name_from_the_title_line() -> None:
    # Act
    parsed = parse_notes(_NOTES, _HEADINGS)

    # Assert
    assert parsed.proposed_name == "Планування MVP"


def test_parsed_notes_keep_the_sections_without_the_title() -> None:
    # Act
    parsed = parse_notes(_NOTES, _HEADINGS)

    # Assert
    assert parsed.content.startswith("## Підсумок\n")


def test_notes_wrapped_in_a_code_fence_are_unwrapped() -> None:
    # Arrange
    fenced = f"```markdown\n{_NOTES}```"

    # Act
    parsed = parse_notes(fenced, _HEADINGS)

    # Assert
    assert parsed.proposed_name == "Планування MVP"


def test_headings_may_differ_in_case_and_a_trailing_colon() -> None:
    # Arrange
    notes = _NOTES.replace("## Рішення", "## рішення:")

    # Act
    parsed = parse_notes(notes, _HEADINGS)

    # Assert
    assert parsed.proposed_name == "Планування MVP"


def test_subsections_inside_a_section_are_allowed() -> None:
    # Arrange
    notes = _NOTES.replace("## Рішення", "### Деталі\n- деталі розмови.\n\n## Рішення")

    # Act
    parsed = parse_notes(notes, _HEADINGS)

    # Assert
    assert "### Деталі" in parsed.content


@pytest.mark.parametrize(
    "length",
    [
        pytest.param(1, id="bva-min"),
        pytest.param(2, id="bva-above-min"),
        pytest.param(100, id="bva-nominal"),
        pytest.param(199, id="bva-below-max"),
        pytest.param(200, id="bva-max"),
    ],
)
def test_title_of_1_to_200_characters_becomes_the_name(length: int) -> None:
    # Arrange
    notes = _NOTES.replace("Планування MVP", "x" * length)

    # Act
    parsed = parse_notes(notes, _HEADINGS)

    # Assert
    assert parsed.proposed_name == "x" * length


def test_title_spaces_are_collapsed_before_its_length_is_counted() -> None:
    # Arrange
    notes = _NOTES.replace("Планування MVP", f"{'x' * 100}   {'x' * 99}  ")

    # Act
    parsed = parse_notes(notes, _HEADINGS)

    # Assert
    assert parsed.proposed_name == f"{'x' * 100} {'x' * 99}"


@pytest.mark.parametrize(
    "notes",
    [
        pytest.param(_NOTES.removeprefix("# Планування MVP\n"), id="no title"),
        pytest.param(_NOTES.replace("## Рішення", "## Висновки"), id="unknown section"),
        pytest.param(_NOTES.split("## Рішення", maxsplit=1)[0], id="missing section"),
        pytest.param(
            "# Планування MVP\n\n## Рішення\n- x\n\n## Підсумок\n- пояснення.",
            id="sections reordered",
        ),
        pytest.param(_NOTES.replace("Планування MVP", "x" * 201), id="name too long"),
        pytest.param(_NOTES.replace("# Планування MVP", "# "), id="empty name"),
    ],
)
def test_notes_that_break_the_format_are_refused_as_invalid_output(notes: str) -> None:
    # Act / Assert
    with pytest.raises(NotesError) as raised:
        parse_notes(notes, _HEADINGS)
    assert raised.value.reason is NotesFailure.INVALID_OUTPUT
