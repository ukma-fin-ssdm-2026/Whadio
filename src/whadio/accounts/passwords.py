from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


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
