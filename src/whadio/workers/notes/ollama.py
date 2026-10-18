from datetime import timedelta
from typing import Final

import httpx2
from pydantic import BaseModel, Field, JsonValue, ValidationError

from ...contracts.notes import NotesFailure, NotesProvider
from .errors import NotesError
from .llm import Completion
from .prompt import Prompt

_CHAT_PATH: Final = "/api/chat"
_BAD_REQUEST: Final = 400
_NOT_FOUND: Final = 404
_FIRST_SERVER_ERROR: Final = 500
_CUT_OFF: Final = "length"


class _Message(BaseModel):
    content: str = Field(description="Text of the answer")


class _ErrorResponse(BaseModel):
    error: str = Field(description="Why the runtime refused the request")


class _ChatResponse(BaseModel):
    model: str = Field(min_length=1, description="Model that served the request")
    message: _Message = Field(description="The assistant's answer")
    done: bool = Field(description="Whether the runtime finished the answer")
    done_reason: str | None = Field(
        default=None, description="Why generation stopped: stop at the end, length when cut off"
    )
    eval_count: int | None = Field(default=None, description="Tokens of the generated answer")


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
        _check_status(response)
        try:
            answer = _ChatResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise NotesError(NotesFailure.INVALID_OUTPUT) from error
        if not answer.done:
            raise NotesError(NotesFailure.INVALID_OUTPUT)
        # A cut-off answer can already hold every heading, so parse_notes would accept it.
        if answer.done_reason == _CUT_OFF:
            raise NotesError(self._cut_off_reason(answer.eval_count))
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
            # By default Ollama cuts a prompt over num_ctx to about half the window and shifts the
            # context while answering, and both silently drop part of the transcript.
            "truncate": False,
            "shift": False,
            "options": {"num_ctx": self._num_ctx, "num_predict": self._num_predict},
        }

    def _cut_off_reason(self, eval_count: int | None) -> NotesFailure:
        # Without context shift, an answer stopped short of num_predict ran out of the window.
        if eval_count is not None and eval_count < self._num_predict:
            return NotesFailure.TRANSCRIPT_TOO_LONG
        return NotesFailure.INVALID_OUTPUT


def _check_status(response: httpx2.Response) -> None:
    status = response.status_code
    # Ollama answers 404 for a model that is not pulled: a deployment fault, not a bad request.
    if status == _NOT_FOUND or status >= _FIRST_SERVER_ERROR:
        raise NotesError(NotesFailure.PROVIDER_UNAVAILABLE)
    if status == _BAD_REQUEST and _exceeds_context(response.content):
        raise NotesError(NotesFailure.TRANSCRIPT_TOO_LONG)
    if not httpx2.codes.is_success(status):
        raise NotesError(NotesFailure.PROVIDER_REJECTED_REQUEST)


def _exceeds_context(body: bytes) -> bool:
    # Ollama and llama-server set a prompt over the window apart from other 400s only by wording.
    try:
        message = _ErrorResponse.model_validate_json(body).error
    except ValidationError:
        return False
    return "context" in message.lower()
