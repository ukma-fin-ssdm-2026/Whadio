import pytest

from .passwords import is_password_strong


@pytest.mark.parametrize(
    "password",
    [
        "abc123",
        "abcdefghijklmn",
        "abcdefghijk1m",
    ],
)
def test_weak_password_is_not_strong(password: str) -> None:
    # Act
    result = is_password_strong(password)

    # Assert
    assert result is False
