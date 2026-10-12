from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    name: str
    email: str
