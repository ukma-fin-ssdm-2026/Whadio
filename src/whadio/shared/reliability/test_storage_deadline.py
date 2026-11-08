import io
import logging
import socket
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from http import HTTPStatus
from typing import Final, override
from uuid import uuid4

import pytest
import urllib3
from minio.error import ServerError
from pydantic import HttpUrl, JsonValue, SecretStr

from conftest import refused_fields

from ..storage import (
    Backoff,
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStorage,
    bounded_pool,
    connect_s3_storage,
    create_s3_client,
)

_KEY = "recordings/5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9"
_AUDIO = b"\x1aE\xdf\xa3webm"
_ATTEMPTS = 3
_ATTEMPT_LIMITS = [
    pytest.param(1, id="bva-min"),
    pytest.param(_ATTEMPTS, id="default"),
    pytest.param(5, id="bva-max"),
]
_BODIES: Final = {
    HTTPStatus.OK: _AUDIO,
    HTTPStatus.FORBIDDEN: b"<Error><Code>AccessDenied</Code></Error>",
    HTTPStatus.SERVICE_UNAVAILABLE: b"<Error><Code>SlowDown</Code></Error>",
}


@dataclass(frozen=True)
class _Server:
    url: HttpUrl
    connections: list[socket.socket]


@contextmanager
def _serving(answer: Callable[[socket.socket], None]) -> Generator[_Server]:
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.01)
    server = _Server(HttpUrl(f"http://127.0.0.1:{listener.getsockname()[1]}"), [])
    stopping = threading.Event()

    def accept() -> None:
        # Ends only once no connection is waiting, so each one made before the stop is counted.
        while True:
            try:
                connection = listener.accept()[0]
            except TimeoutError:
                if stopping.is_set():
                    return
                continue
            server.connections.append(connection)
            answer(connection)

    accepting = threading.Thread(target=accept)
    accepting.start()
    try:
        yield server
    finally:
        stopping.set()
        accepting.join()
        for connection in [*server.connections, listener]:
            connection.close()


def _stay_silent(connection: socket.socket) -> None:
    del connection


type _Answer = HTTPStatus | urllib3.exceptions.HTTPError | ServerError


class _ScriptedPool(urllib3.PoolManager):
    """Answers each request with the next of `answers`, and every later one with the last."""

    def __init__(self, *answers: _Answer) -> None:
        super().__init__()
        self.requests: int = 0
        self._answers: tuple[_Answer, ...] = answers

    @override
    def urlopen(
        self, method: str, url: str, redirect: bool = True, **kw: object
    ) -> urllib3.BaseHTTPResponse:
        answer = self._answers[min(self.requests, len(self._answers) - 1)]
        self.requests += 1
        # minio 7.2 raises ServerError for a 5xx only on HEAD; for get and delete only a double can.
        if not isinstance(answer, HTTPStatus):
            raise answer
        return urllib3.HTTPResponse(
            body=io.BytesIO(_BODIES[answer]),
            status=answer,
            headers={"Content-Type": "application/xml"},
            preload_content=False,
        )


@dataclass
class _Jitter:
    ranges: list[tuple[float, float]] = field(default_factory=list[tuple[float, float]])
    slept: list[float] = field(default_factory=list[float])

    def uniform(self, low: float, high: float) -> float:
        self.ranges.append((low, high))
        return (low + high) / 2

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def _settings(endpoint_url: HttpUrl) -> ObjectStorageSettings:
    return ObjectStorageSettings(
        endpoint_url=endpoint_url,
        access_key=SecretStr("whadio-test"),
        secret_key=SecretStr("whadio-test-secret"),
        timeout=timedelta(milliseconds=50),
        attempts=_ATTEMPTS,
    )


def _storage_on(
    pool: _ScriptedPool, *, attempts: int = _ATTEMPTS, jitter: _Jitter | None = None
) -> S3ObjectStorage:
    waits = jitter or _Jitter()
    settings = _settings(HttpUrl("http://storage.test:8333"))
    client = create_s3_client(settings, settings.endpoint_url, http_client=pool)
    return S3ObjectStorage(
        client=client,
        signer=client,
        bucket=settings.bucket,
        backoff=Backoff(attempts, uniform=waits.uniform, sleep=waits.sleep),
    )


def _configured[T](pool: urllib3.PoolManager, name: str, kind: type[T]) -> T:
    value = pool.connection_pool_kw.get(name)
    if not isinstance(value, kind):
        raise TypeError(f"the pool has no {kind.__name__} {name}")
    return value


def _timed_out() -> urllib3.exceptions.ReadTimeoutError:
    pool = urllib3.HTTPConnectionPool("storage.test")
    return urllib3.exceptions.ReadTimeoutError(pool, "/", "Read timed out.")


def _get(storage: S3ObjectStorage) -> None:
    storage.get(_KEY)


def _delete(storage: S3ObjectStorage) -> None:
    storage.delete(_KEY)


def _put(storage: S3ObjectStorage) -> None:
    storage.put(_KEY, io.BytesIO(_AUDIO), content_type="audio/webm")


@pytest.mark.parametrize(
    ("answer", "call"),
    [
        pytest.param(_stay_silent, _get, id="get-from-a-store-that-never-answers"),
        pytest.param(socket.socket.close, _delete, id="delete-on-a-store-that-hangs-up-at-once"),
    ],
)
def test_call_to_a_failing_store_is_given_up_after_its_attempts(
    answer: Callable[[socket.socket], None], call: Callable[[S3ObjectStorage], None]
) -> None:
    # Arrange
    with _serving(answer) as server:
        storage = connect_s3_storage(_settings(server.url), sleep=_Jitter().sleep)

        # Act
        with pytest.raises(ObjectStorageError):
            call(storage)

    # Assert
    assert len(server.connections) == _ATTEMPTS


def test_get_that_times_out_on_every_attempt_logs_one_warning_without_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    storage = _storage_on(_ScriptedPool(_timed_out()))

    # Act
    with caplog.at_level(logging.WARNING), pytest.raises(ObjectStorageError):
        storage.get(_KEY)

    # Assert
    assert [(record.levelno, record.getMessage()) for record in caplog.records] == [
        (logging.WARNING, f"Reading an object failed after {_ATTEMPTS} attempts")
    ]


@pytest.mark.parametrize(
    ("status", "call"),
    [
        pytest.param(HTTPStatus.FORBIDDEN, _get, id="get-access-denied"),
        pytest.param(HTTPStatus.SERVICE_UNAVAILABLE, _put, id="put-service-unavailable"),
    ],
)
def test_request_is_sent_once_when_a_repeat_is_futile_or_unsafe(
    status: HTTPStatus, call: Callable[[S3ObjectStorage], None]
) -> None:
    # Arrange
    pool = _ScriptedPool(status)

    # Act
    with pytest.raises(ObjectStorageError):
        call(_storage_on(pool))

    # Assert
    assert pool.requests == 1


@pytest.mark.parametrize("attempts", _ATTEMPT_LIMITS)
def test_get_that_succeeds_on_the_last_attempt_returns_the_object(attempts: int) -> None:
    # Arrange
    pool = _ScriptedPool(*[_timed_out()] * (attempts - 1), HTTPStatus.OK)

    # Act
    found = _storage_on(pool, attempts=attempts).get(_KEY)

    # Assert
    assert found == _AUDIO


@pytest.mark.parametrize("attempts", _ATTEMPT_LIMITS)
def test_get_that_would_succeed_one_attempt_later_raises(attempts: int) -> None:
    # Arrange
    pool = _ScriptedPool(*[_timed_out()] * attempts, HTTPStatus.OK)

    # Act / Assert
    with pytest.raises(ObjectStorageError, match="Reading an object failed"):
        _storage_on(pool, attempts=attempts).get(_KEY)


_OPERATIONS = [pytest.param(_get, id="get"), pytest.param(_delete, id="delete")]
_SERVER_FAILURES = [
    pytest.param(HTTPStatus.SERVICE_UNAVAILABLE, id="s3-error-503"),
    pytest.param(
        ServerError("server failed", HTTPStatus.SERVICE_UNAVAILABLE), id="server-error-503"
    ),
]


@pytest.mark.parametrize("failure", _SERVER_FAILURES)
@pytest.mark.parametrize("call", _OPERATIONS)
def test_call_answered_5xx_recovers_on_its_last_attempt(
    call: Callable[[S3ObjectStorage], None], failure: _Answer
) -> None:
    # Arrange
    pool = _ScriptedPool(*[failure] * (_ATTEMPTS - 1), HTTPStatus.OK)

    # Act
    call(_storage_on(pool))

    # Assert
    assert pool.requests == _ATTEMPTS


@pytest.mark.parametrize("failure", _SERVER_FAILURES)
@pytest.mark.parametrize("call", _OPERATIONS)
def test_call_answered_5xx_every_time_gives_up_after_its_attempts(
    call: Callable[[S3ObjectStorage], None], failure: _Answer
) -> None:
    # Arrange
    pool = _ScriptedPool(failure)

    # Act
    with pytest.raises(ObjectStorageError):
        call(_storage_on(pool))

    # Assert
    assert pool.requests == _ATTEMPTS


def test_wait_before_retry_n_is_drawn_up_to_a_quarter_second_doubled_n_times() -> None:
    # Arrange
    jitter = _Jitter()
    storage = _storage_on(_ScriptedPool(_timed_out()), attempts=4, jitter=jitter)

    # Act
    with pytest.raises(ObjectStorageError):
        storage.get(_KEY)

    # Assert
    assert (jitter.ranges, jitter.slept) == (
        [(0.0, 0.25), (0.0, 0.5), (0.0, 1.0)],
        [0.125, 0.25, 0.5],
    )


@pytest.mark.parametrize(
    "retry",
    [
        pytest.param(3, id="at-the-cap"),
        pytest.param(4, id="past-the-cap"),
        pytest.param(20, id="far-past-the-cap"),
    ],
)
def test_wait_stops_growing_at_two_seconds(retry: int) -> None:
    # Arrange
    jitter = _Jitter()
    backoff = Backoff(5, uniform=jitter.uniform, sleep=jitter.sleep)

    # Act
    backoff.wait(retry)

    # Assert
    assert jitter.ranges == [(0.0, 2.0)]


def test_pool_waits_the_timeout_to_connect_and_for_each_read_and_retries_nothing() -> None:
    # Arrange
    pool = bounded_pool(_settings(HttpUrl("http://storage.test:8333")))

    # Act
    timeout = _configured(pool, "timeout", urllib3.Timeout)
    retries = _configured(pool, "retries", urllib3.Retry)

    # Assert
    assert (timeout.connect_timeout, timeout.read_timeout, retries.total) == (0.05, 0.05, False)


@pytest.mark.parametrize(
    ("name", "value", "refused"),
    [
        pytest.param("timeout", "PT0S", {"timeout"}, id="timeout-bva-below-min"),
        pytest.param("timeout", "PT0.001S", set[str](), id="timeout-bva-min"),
        pytest.param("attempts", 0, {"attempts"}, id="attempts-bva-below-min"),
        pytest.param("attempts", 1, set[str](), id="attempts-bva-min"),
        pytest.param("attempts", 5, set[str](), id="attempts-bva-max"),
        pytest.param("attempts", 6, {"attempts"}, id="attempts-bva-above-max"),
    ],
)
def test_storage_settings_bound_the_timeout_and_the_attempts(
    name: str, value: JsonValue, refused: set[str]
) -> None:
    # Arrange
    data: dict[str, JsonValue] = {
        "endpoint_url": "http://seaweedfs:8333",
        "access_key": "whadio-test",
        "secret_key": uuid4().hex,
        name: value,
    }

    # Act
    found = refused_fields(ObjectStorageSettings, data)

    # Assert
    assert found == refused
