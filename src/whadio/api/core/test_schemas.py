import unicodedata
from typing import Final

from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from .schemas import DisplayText

_DISPLAY_TEXT: Final = TypeAdapter[str](DisplayText)
_BLANK_GRAPHICS: Final = frozenset("ᅟᅠㅤﾠ⠀")
_PADDING: Final = st.text(
    st.characters(categories=["Zs", "Zl", "Zp"], include_characters="\t\n\v\f\r\x85"), max_size=3
)
# Arbitrary text around one visible character: most inputs are accepted, yet control characters
# and invisible ones still appear, so no input has to be filtered out.
_RAW_TEXT: Final = st.tuples(
    _PADDING, st.text(), st.characters(categories=["L", "N", "P", "S"]), st.text(), _PADDING
).map("".join)
# Hypothesis merges a one_of of character strategies into one code-point range, where the five
# blank graphics would almost never be drawn; a one_of of whole texts keeps them in play.
_INVISIBLE_TEXT: Final = st.one_of(
    st.text(st.characters(exclude_categories=["L", "N", "P", "S", "Cs"])),
    st.text(st.sampled_from(sorted(_BLANK_GRAPHICS)), min_size=1),
)


def _validated(value: str) -> str | None:
    try:
        return _DISPLAY_TEXT.validate_python(value)
    except ValidationError:
        return None


def _is_visible(char: str) -> bool:
    return unicodedata.category(char)[0] in "LNPS" and char not in _BLANK_GRAPHICS


@given(_RAW_TEXT)
def test_accepted_display_text_is_stripped(value: str) -> None:
    # Act
    accepted = _validated(value)

    # Assert
    assert accepted is None or accepted == accepted.strip()


@given(_INVISIBLE_TEXT)
@example("")
@example(" \t ")
@example("\u200b")
def test_display_text_without_a_visible_character_is_rejected(value: str) -> None:
    # Act
    accepted = _validated(value)

    # Assert
    assert accepted is None


@given(_RAW_TEXT)
def test_accepted_display_text_has_no_control_character(value: str) -> None:
    # Act
    accepted = _validated(value)

    # Assert
    assert accepted is None or all(unicodedata.category(char) != "Cc" for char in accepted)


@given(_RAW_TEXT)
def test_accepted_display_text_has_a_visible_character(value: str) -> None:
    # Act
    accepted = _validated(value)

    # Assert
    assert accepted is None or any(_is_visible(char) for char in accepted)


@given(_RAW_TEXT)
def test_validating_accepted_display_text_again_returns_it_unchanged(value: str) -> None:
    # Arrange
    accepted = _validated(value)

    # Act
    again = None if accepted is None else _validated(accepted)

    # Assert
    assert again == accepted
