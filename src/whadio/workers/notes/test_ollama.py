import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

import httpx2
import pytest
from pydantic import Field, HttpUrl, JsonValue, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...contracts.notes import NotesFailure, NotesProvider
from .errors import NotesError
from .llm import Completion
from .ollama import OllamaChatModel
from .prompt import Prompt

_PROMPT = Prompt(
    system="Write notes.", user="<meeting>...</meeting>", headings=(), context_meeting_ids=()
)
_NUM_CTX = 8192
_BODY = TypeAdapter(dict[str, JsonValue])

type _Handler = Callable[[httpx2.Request], httpx2.Response]


def _chat(
    content: str = "# Sync\n## Summary\nShort.",
    *,
    model: str = "gemma3:12b",
    prompt_eval_count: int = 120,
) -> dict[str, JsonValue]:
    return {
        "model": model,
        "created_at": "2026-10-18T12:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": prompt_eval_count,
        "eval_count": 40,
    }


def _answering(status: int, body: dict[str, JsonValue]) -> _Handler:
    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return handle


def _model(client: httpx2.AsyncClient, *, num_ctx: int = _NUM_CTX) -> OllamaChatModel:
    return OllamaChatModel(
        client,
        model="gemma3:12b",
        num_ctx=num_ctx,
        num_predict=2048,
        keep_alive=timedelta(minutes=5),
    )


def _complete(handler: _Handler) -> Completion:
    async def complete() -> Completion:
        transport = httpx2.MockTransport(handler)
        async with httpx2.AsyncClient(transport=transport, base_url="http://ollama") as client:
            return await _model(client).complete(_PROMPT)

    return asyncio.run(complete())


def _failure_of(handler: _Handler) -> NotesFailure:
    with pytest.raises(NotesError) as raised:
        _complete(handler)
    return raised.value.reason


def test_ollama_reports_the_whadio_provider() -> None:
    # Arrange
    client = httpx2.AsyncClient()

    # Act
    provider = _model(client).provider

    # Assert
    assert provider is NotesProvider.WHADIO


def test_ollama_returns_the_content_of_its_answer() -> None:
    # Arrange
    handler = _answering(200, _chat("# Sync\n## Summary\nShort."))

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.text == "# Sync\n## Summary\nShort."


def test_ollama_names_the_model_that_served_the_request() -> None:
    # Arrange
    handler = _answering(200, _chat(model="gemma3:12b-it-qat"))

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.model_name == "gemma3:12b-it-qat"


def test_ollama_request_asks_for_one_unthinking_answer_within_the_window() -> None:
    # Arrange
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=_chat())

    # Act
    _complete(handle)

    # Assert
    [request] = requests
    assert (request.url.path, _BODY.validate_json(request.content)) == (
        "/api/chat",
        {
            "model": "gemma3:12b",
            "messages": [
                {"role": "system", "content": "Write notes."},
                {"role": "user", "content": "<meeting>...</meeting>"},
            ],
            "stream": False,
            "think": False,
            "keep_alive": 300,
            "options": {"num_ctx": 8192, "num_predict": 2048},
        },
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, NotesFailure.PROVIDER_REJECTED_REQUEST),
        (404, NotesFailure.PROVIDER_UNAVAILABLE),
        (500, NotesFailure.PROVIDER_UNAVAILABLE),
        (503, NotesFailure.PROVIDER_UNAVAILABLE),
    ],
)
def test_ollama_error_status_maps_to_a_notes_failure(status: int, expected: NotesFailure) -> None:
    # Arrange
    handler = _answering(status, {"error": "refused"})

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is expected


def test_ollama_that_cannot_be_reached_is_reported_as_unavailable() -> None:
    # Arrange
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    # Act
    reason = _failure_of(handle)

    # Assert
    assert reason is NotesFailure.PROVIDER_UNAVAILABLE


def test_ollama_that_answers_too_late_is_reported_as_timed_out() -> None:
    # Arrange
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("no answer", request=request)

    # Act
    reason = _failure_of(handle)

    # Assert
    assert reason is NotesFailure.TIMED_OUT


@pytest.mark.parametrize("content", ["", " \n\t"], ids=["empty", "whitespace"])
def test_ollama_answer_without_text_is_invalid_output(content: str) -> None:
    # Arrange
    handler = _answering(200, _chat(content))

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.INVALID_OUTPUT


def test_ollama_answer_of_an_unexpected_shape_is_invalid_output() -> None:
    # Arrange
    handler = _answering(200, {"model": "gemma3:12b", "done": True})

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.INVALID_OUTPUT


@pytest.mark.parametrize("prompt_eval_count", [_NUM_CTX, _NUM_CTX + 1], ids=["at", "above"])
def test_ollama_prompt_filling_the_window_is_reported_as_too_long(prompt_eval_count: int) -> None:
    # Arrange
    handler = _answering(200, _chat(prompt_eval_count=prompt_eval_count))

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.TRANSCRIPT_TOO_LONG


def test_ollama_prompt_just_inside_the_window_is_answered() -> None:
    # Arrange
    handler = _answering(200, _chat("# Sync", prompt_eval_count=_NUM_CTX - 1))

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.text == "# Sync"


def test_ollama_answer_without_a_prompt_count_is_answered() -> None:
    # Arrange
    body = _chat("# Sync")
    del body["prompt_eval_count"]
    handler = _answering(200, body)

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.text == "# Sync"


# --- Against a real Ollama ---


class OllamaTestSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WHADIO_TEST_")

    ollama_url: HttpUrl | None = Field(
        default=None, description="Address of an Ollama server for integration tests"
    )
    ollama_model: str | None = Field(
        default=None, min_length=1, description="Tag of a model already pulled on that server"
    )


@dataclass(frozen=True, slots=True)
class LiveOllama:
    url: HttpUrl
    model: str

    def complete(self, prompt: Prompt, *, num_ctx: int) -> Completion:
        async def complete() -> Completion:
            async with httpx2.AsyncClient(base_url=str(self.url), timeout=300) as client:
                model = OllamaChatModel(
                    client,
                    model=self.model,
                    num_ctx=num_ctx,
                    num_predict=256,
                    keep_alive=timedelta(minutes=1),
                )
                return await model.complete(prompt)

        return asyncio.run(complete())


@pytest.fixture
def live_ollama() -> LiveOllama:
    settings = OllamaTestSettings()
    if settings.ollama_url is None or settings.ollama_model is None:
        pytest.skip(
            "Set WHADIO_TEST_OLLAMA_URL and WHADIO_TEST_OLLAMA_MODEL to run the tests against "
            "a real Ollama"
        )
    return LiveOllama(settings.ollama_url, settings.ollama_model)


@pytest.mark.slow
def test_real_ollama_answers_a_short_prompt(live_ollama: LiveOllama) -> None:
    # Arrange
    prompt = Prompt(
        system="Answer in one short sentence.",
        user="Name a colour of the sky on a clear day.",
        headings=(),
        context_meeting_ids=(),
    )

    # Act
    completion = live_ollama.complete(prompt, num_ctx=4096)

    # Assert
    assert completion.text.strip()


@pytest.mark.slow
def test_real_ollama_prompt_longer_than_the_window_is_reported_as_too_long(
    live_ollama: LiveOllama,
) -> None:
    # Arrange
    prompt = Prompt(
        system="Summarise the meeting.",
        user="<meeting>" + "Speaker 1: we agreed on the plan. " * 400 + "</meeting>",
        headings=(),
        context_meeting_ids=(),
    )

    # Act
    with pytest.raises(NotesError) as raised:
        live_ollama.complete(prompt, num_ctx=512)

    # Assert
    assert raised.value.reason is NotesFailure.TRANSCRIPT_TOO_LONG
