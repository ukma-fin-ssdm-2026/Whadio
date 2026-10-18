from datetime import timedelta
from typing import Final

import httpx2
from pydantic import BaseModel, Field, JsonValue, ValidationError

from ...contracts.notes import NotesFailure, NotesProvider
from .errors import NotesError
from .llm import Completion
from .prompt import Prompt

_CHAT_PATH: Final = "/api/chat"
_NOT_FOUND: Final = 404
_FIRST_SERVER_ERROR: Final = 500
_CUT_OFF: Final = "length"


class _Message(BaseModel):
    content: str = Field(description="Text of the answer")


class _ChatResponse(BaseModel):
    model: str = Field(min_length=1, description="Model that served the request")
    message: _Message = Field(description="The assistant's answer")
    done: bool = Field(description="Whether the runtime finished the answer")
    done_reason: str | None = Field(
        default=None, description="Why generation stopped: stop at the end, length when cut off"
    )
    prompt_eval_count: int | None = Field(
        default=None, description="Tokens of the prompt the runtime evaluated"
    )


class OllamaChatModel:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        model: str,
        num_ctx: int,
        num_predict: int,
        keep_alive: timedelta,
    ) -> None:
        self._client: httpx2.AsyncClient = client
        self._model: str = model
        self._num_ctx: int = num_ctx
        self._num_predict: int = num_predict
        self._keep_alive: timedelta = keep_alive

    @property
    def provider(self) -> NotesProvider:
        return NotesProvider.WHADIO

    async def complete(self, prompt: Prompt) -> Completion:
        try:
            response = await self._client.post(_CHAT_PATH, json=self._request(prompt))
        except httpx2.TimeoutException as error:
            raise NotesError(NotesFailure.TIMED_OUT) from error
        except httpx2.TransportError as error:
            raise NotesError(NotesFailure.PROVIDER_UNAVAILABLE) from error
        _check_status(response.status_code)
        try:
            answer = _ChatResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise NotesError(NotesFailure.INVALID_OUTPUT) from error
        # Ollama cuts a prompt longer than num_ctx without an error, so notes would cover only
        # part of the transcript.
        if answer.prompt_eval_count is not None and answer.prompt_eval_count >= self._num_ctx:
            raise NotesError(NotesFailure.TRANSCRIPT_TOO_LONG)
        # A cut-off answer can already hold every heading, so parse_notes would accept it.
        if not answer.done or answer.done_reason == _CUT_OFF:
            raise NotesError(NotesFailure.INVALID_OUTPUT)
        if not answer.message.content.strip():
            raise NotesError(NotesFailure.INVALID_OUTPUT)
        return Completion(text=answer.message.content, model_name=answer.model)

    def _request(self, prompt: Prompt) -> dict[str, JsonValue]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "stream": False,
            "think": False,
            "keep_alive": round(self._keep_alive.total_seconds()),
            "options": {"num_ctx": self._num_ctx, "num_predict": self._num_predict},
        }


def _check_status(status: int) -> None:
    # Ollama answers 404 for a model that is not pulled: a deployment fault, not a bad request.
    if status == _NOT_FOUND or status >= _FIRST_SERVER_ERROR:
        raise NotesError(NotesFailure.PROVIDER_UNAVAILABLE)
    if not httpx2.codes.is_success(status):
        raise NotesError(NotesFailure.PROVIDER_REJECTED_REQUEST)
