from typing import Final, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH: Final = 12
MAX_PASSWORD_LENGTH: Final = 128


class IPasswordHasher(Protocol):
    def hash(self, password: str, /) -> str: ...

    def verify(self, password_hash: str, password: str, /) -> bool: ...


class Argon2PasswordHasher:
    """Argon2id with the library's recommended cost parameters (RFC 9106, second choice)."""

    def __init__(self) -> None:
        self._hasher: PasswordHasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False


def is_password_strong(password: str) -> bool:
    try:
        password.encode()
    except UnicodeEncodeError:
        return False
    return (
        MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
        and any(character.isdigit() for character in password)
        and any(character.isupper() for character in password)
    )


def password_rule_message() -> str:
    return "Use 12 to 128 characters, at least one digit and one uppercase letter"
