from enum import StrEnum


class Failure(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    DEFAULT_FOLDER = "DEFAULT_FOLDER"


class UseCaseError(Exception):
    def __init__(self, code: Failure) -> None:
        self.code: Failure = code
        super().__init__(code.value)
