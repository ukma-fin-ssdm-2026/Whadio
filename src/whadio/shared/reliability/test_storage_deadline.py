import socket
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import HttpUrl, JsonValue, SecretStr

from conftest import refused_fields

from ..storage import ObjectStorageError, ObjectStorageSettings, S3ObjectStorage, connect_s3_storage

_KEY = "recordings/5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9"


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


def _settings(endpoint_url: HttpUrl) -> ObjectStorageSettings:
    return ObjectStorageSettings(
        endpoint_url=endpoint_url,
        access_key=SecretStr("whadio-test"),
        secret_key=SecretStr("whadio-test-secret"),
        timeout=timedelta(milliseconds=50),
    )


def _get(storage: S3ObjectStorage) -> None:
    storage.get(_KEY)


@pytest.mark.parametrize(
    ("answer", "call"),
    [pytest.param(_stay_silent, _get, id="get-from-a-store-that-never-answers")],
)
def test_call_to_a_failing_store_is_given_up_after_its_attempts(
    answer: Callable[[socket.socket], None], call: Callable[[S3ObjectStorage], None]
) -> None:
    # Arrange
    with _serving(answer) as server:
        storage = connect_s3_storage(_settings(server.url))

        # Act
        with pytest.raises(ObjectStorageError):
            call(storage)

    # Assert
    assert len(server.connections) == 1


@pytest.mark.parametrize(
    ("field", "value", "refused"),
    [
        pytest.param("timeout", "PT0S", {"timeout"}, id="timeout-bva-below-min"),
        pytest.param("timeout", "PT0.001S", set[str](), id="timeout-bva-min"),
    ],
)
def test_storage_settings_bound_the_timeout_and_the_attempts(
    field: str, value: JsonValue, refused: set[str]
) -> None:
    # Arrange
    data: dict[str, JsonValue] = {
        "endpoint_url": "http://seaweedfs:8333",
        "access_key": "whadio-test",
        "secret_key": uuid4().hex,
        field: value,
    }

    # Act
    found = refused_fields(ObjectStorageSettings, data)

    # Assert
    assert found == refused
