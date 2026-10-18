import pytest

from .text import display_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Sprint review", "Sprint review"),
        ("\u041e\u0433\u043b\u044f\u0434", "\u041e\u0433\u043b\u044f\u0434"),
        ("0\xad", "0\xad"),
        ("0\U0001239a", "0\U0001239a"),
        ("  Sprint review\t\n", "Sprint review"),
        ("\u3000Sprint\xa0review\u2028", "Sprint\xa0review"),
    ],
    ids=["plain", "cyrillic", "soft-hyphen", "unassigned", "padded", "unicode-padded"],
)
def test_displayable_text_is_returned_without_surrounding_white_space(
    value: str, expected: str
) -> None:
    # Act
    result = display_text(value)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    "value",
    ["0\x1f", "\x1cSprint", "Sprint\nreview", "Sprint\x07review", "Sprint\x85\x9freview"],
    ids=["unit-separator", "file-separator", "line-break", "bell", "c1-control"],
)
def test_text_with_a_control_character_is_refused(value: str) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="control characters"):
        display_text(value)


@pytest.mark.parametrize(
    "value",
    ["", "   ", "\xad", "\u200b\u200d", "\u3164\u2800", "\U0001239a"],
    ids=["empty", "spaces", "soft-hyphen", "zero-width", "blank-graphics", "unassigned"],
)
def test_text_without_a_visible_character_is_refused(value: str) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="visible character"):
        display_text(value)
