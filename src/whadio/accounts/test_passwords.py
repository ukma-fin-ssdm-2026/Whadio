import pytest

from .passwords import is_password_strong


@pytest.mark.parametrize(
    "password",
    [
        "abc123",
        "abcdefghijklmn",
    ],
)
def test_weak_password_is_not_strong(password: str) -> None:
    result = is_password_strong(password)
    assert result is False
