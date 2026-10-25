import pytest

from .passwords import is_password_strong


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefghij1",
        "Abcdefghijkl",
        "abcdefghijk1",
        "Abcdefghijk1" + "m" * 117,
    ],
)
def test_weak_password_is_not_strong(password: str) -> None:
    # Act
    result = is_password_strong(password)

    # Assert
    assert result is False


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefghijk1",
        "Correct1HorseBatteryStaple",
        "Abcdefghijk1" + "m" * 116,
    ],
)
def test_password_with_length_digit_and_uppercase_is_strong(password: str) -> None:
    # Act
    result = is_password_strong(password)

    # Assert
    assert result is True
