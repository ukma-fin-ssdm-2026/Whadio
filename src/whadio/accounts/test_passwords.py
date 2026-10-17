import pytest

from .passwords import is_password_strong

def test_short_password_is_weak() -> None:
    password = "abc123"
    result = is_password_strong(password)
    assert result is False

@pytest.mark.xfail(strict=True)
def test_password_without_digit_is_weak() -> None:
    password = "abcdefghijklmn"
    result = is_password_strong(password)
    assert result is False
