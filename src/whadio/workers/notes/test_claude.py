import asyncio
from collections.abc import Callable

import anthropic
import httpx2
import pytest
from pydantic import JsonValue, TypeAdapter

from ...contracts.notes import NotesFailure
from .claude import ClaudeChatModel
from .errors import NotesError
from .llm import Completion
from .prompt import Prompt

_PROMPT = Prompt(
    system="Write notes.", user="<meeting>...</meeting>", headings=(), context_meeting_ids=()
)
_BODY = TypeAdapter(dict[str, JsonValue])

type _Handler = Callable[[httpx2.Request], httpx2.Response]


def _message(
    *content: dict[str, JsonValue], stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5"
) -> dict[str, JsonValue]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": list(content),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


def _answering(status: int, body: dict[str, JsonValue]) -> _Handler:
    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return handle


def _error() -> dict[str, JsonValue]:
    return {"type": "error", "error": {"type": "api_error", "message": "refused"}}


def _model(handler: _Handler) -> ClaudeChatModel:
    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeChatModel(
        client, model="claude-sonnet-5-5", max_output_tokens=16000, effort="medium"
    )


def _complete(handler: _Handler) -> Completion:
    return asyncio.run(_model(handler).complete(_PROMPT))


def _failure_of(handler: _Handler) -> NotesFailure:
    with pytest.raises(NotesError) as raised:
        _complete(handler)
    return raised.value.reason


def test_claude_returns_the_text_blocks_of_its_answer() -> None:
    # Arrange
    handler = _answering(
        200,
        _message(
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "# Sync\n"},
            {"type": "text", "text": "## Summary\nShort."},
        ),
    )

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.text == "# Sync\n## Summary\nShort."


def test_claude_names_the_model_that_served_the_request() -> None:
    # Arrange
    handler = _answering(200, _message({"type": "text", "text": "# Sync"}, model="claude-sonnet-5"))

    # Act
    completion = _complete(handler)

    # Assert
    assert completion.model_name == "claude-sonnet-5"


def test_claude_request_opts_into_the_default_server_side_fallback() -> None:
    # Arrange
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=_message({"type": "text", "text": "# Sync"}))

    # Act
    _complete(handle)

    # Assert
    [request] = requests
    assert (
        request.headers["anthropic-beta"],
        _BODY.validate_json(request.content)["fallbacks"],
    ) == ("server-side-fallback-2026-07-01", "default")


def test_claude_refusal_is_reported_as_refused() -> None:
    # Arrange
    handler = _answering(200, _message(stop_reason="refusal"))

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.PROVIDER_REFUSED


def test_claude_answer_cut_off_by_the_answer_limit_is_invalid_output() -> None:
    # Arrange
    handler = _answering(
        200,
        _message(
            {"type": "text", "text": "# Sync\n## Summary\nShould we"}, stop_reason="max_tokens"
        ),
    )

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.INVALID_OUTPUT


def test_claude_answer_that_runs_out_of_the_window_is_reported_as_too_long() -> None:
    # Arrange
    handler = _answering(
        200,
        _message(
            {"type": "text", "text": "# Sync\n## Summary\nShould we"},
            stop_reason="model_context_window_exceeded",
        ),
    )

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is NotesFailure.TRANSCRIPT_TOO_LONG


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, NotesFailure.PROVIDER_REJECTED_REQUEST),
        (401, NotesFailure.PROVIDER_AUTH_FAILED),
        (403, NotesFailure.PROVIDER_AUTH_FAILED),
        (404, NotesFailure.PROVIDER_REJECTED_REQUEST),
        (413, NotesFailure.TRANSCRIPT_TOO_LONG),
        (429, NotesFailure.PROVIDER_RATE_LIMITED),
        (500, NotesFailure.PROVIDER_UNAVAILABLE),
        (529, NotesFailure.PROVIDER_UNAVAILABLE),
    ],
)
def test_claude_error_status_maps_to_a_notes_failure(status: int, expected: NotesFailure) -> None:
    # Arrange
    handler = _answering(status, _error())

    # Act
    reason = _failure_of(handler)

    # Assert
    assert reason is expected


def test_claude_that_cannot_be_reached_is_reported_as_unavailable() -> None:
    # Arrange
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    # Act
    reason = _failure_of(handle)

    # Assert
    assert reason is NotesFailure.PROVIDER_UNAVAILABLE
