import unicodedata
from typing import Final

from hypothesis import given, reject
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from .schemas import DisplayText

_DISPLAY_TEXT: Final = TypeAdapter[str](DisplayText)
_BLANK_GRAPHICS: Final = frozenset("\u115f\u1160\u3164\uffa0\u2800")
_PADDING: Final = st.text(
    st.characters(categories=["Zs", "Zl", "Zp"], include_characters="\t\n\v\f\r\x85"), max_size=3
)
_RAW_TEXT: Final = st.tuples(_PADDING, st.text(), _PADDING).map("".join)


def _accepted(value: str) -> str:
    try:
        return _DISPLAY_TEXT.validate_python(value)
    except ValidationError:
        reject()


def _is_visible(char: str) -> bool:
    return unicodedata.category(char)[0] in "LNPS" and char not in _BLANK_GRAPHICS


@given(_RAW_TEXT)
def test_accepted_display_text_is_stripped(value: str) -> None:
    # Act
    accepted = _accepted(value)

    # Assert
    assert accepted == accepted.strip()


@given(_RAW_TEXT)
def test_accepted_display_text_is_not_empty(value: str) -> None:
    # Act
    accepted = _accepted(value)

    # Assert
    assert accepted


@given(_RAW_TEXT)
def test_accepted_display_text_has_no_control_character(value: str) -> None:
    # Act
    accepted = _accepted(value)

    # Assert
    assert all(unicodedata.category(char) != "Cc" for char in accepted)


@given(_RAW_TEXT)
def test_accepted_display_text_has_a_visible_character(value: str) -> None:
    # Act
    accepted = _accepted(value)

    # Assert
    assert any(_is_visible(char) for char in accepted)


@given(_RAW_TEXT)
def test_validating_accepted_display_text_again_returns_it_unchanged(value: str) -> None:
    # Arrange
    accepted = _accepted(value)

    # Act
    again = _DISPLAY_TEXT.validate_python(accepted)

    # Assert
    assert again == accepted
