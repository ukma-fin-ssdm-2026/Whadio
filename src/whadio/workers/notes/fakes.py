from collections import deque
from typing import override

from ...contracts.notes import NotesProvider
from .errors import NotesError
from .llm import Completion, IChatModel
from .prompt import Prompt

type ScriptedAnswer = str | Completion | NotesError


class ScriptedChatModel(IChatModel):
    def __init__(
        self,
        *answers: ScriptedAnswer,
        provider: NotesProvider = NotesProvider.ANTHROPIC,
        model_name: str = "scripted-model",
    ) -> None:
        self.prompts: list[Prompt] = []
        self._answers: deque[ScriptedAnswer] = deque(answers)
        self._provider: NotesProvider = provider
        self._model_name: str = model_name

    @property
    @override
    def provider(self) -> NotesProvider:
        return self._provider

    @override
    async def complete(self, prompt: Prompt) -> Completion:
        self.prompts.append(prompt)
        if not self._answers:
            raise LookupError(f"the script has no answer for call {len(self.prompts)}")
        answer = self._answers.popleft()
        match answer:
            case NotesError():
                raise answer
            case Completion():
                return answer
            case str():
                return Completion(text=answer, model_name=self._model_name)
