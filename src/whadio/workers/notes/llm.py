from dataclasses import dataclass
from typing import Protocol

from ...contracts.notes import NotesProvider
from .prompt import Prompt


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    model_name: str


class IChatModel(Protocol):
    """A language model behind a provider's API.

    `complete` raises `NotesError` with the provider failure as its reason.
    """

    @property
    def provider(self) -> NotesProvider: ...

    async def complete(self, prompt: Prompt) -> Completion: ...
