import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from .telemetry import Observation, ObservationPublisher, TelemetrySettings


@pytest.mark.parametrize("status", [204, 302])
def test_publisher_posts_source_credentials_without_following_redirects(status: int) -> None:
    # Arrange
    token = uuid4().hex
    observation = Observation(sampled_at=datetime.now(UTC), kind="host", cpu_percent=25)
    received: list[tuple[str, str | None, Observation]] = []

    async def scenario() -> None:
        async def receive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            fields = dict(line.split(": ", 1) for line in headers[1:] if ": " in line)
            body = await reader.readexactly(int(fields["Content-Length"]))
            received.append(
                (
                    headers[0].split()[1],
                    fields.get("Authorization"),
                    Observation.model_validate_json(body),
                )
            )
            writer.write(
                (
                    f"HTTP/1.1 {status} Response\r\nLocation: /stolen\r\n"
                    "Content-Length: 0\r\nConnection: close\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(receive, "127.0.0.1", 0) as server:
            _, port = TypeAdapter(tuple[str, int]).validate_python(server.sockets[0].getsockname())
            settings = TelemetrySettings.model_validate(
                {"receiver": f"http://127.0.0.1:{port}", "source_id": "main-host", "token": token}
            )
            publisher = ObservationPublisher(settings)
            try:
                # Act
                await publisher.publish(observation)
            finally:
                publisher.close()

    asyncio.run(scenario())
    # Assert
    assert received == [("/api/v1/admin/observations/main-host", f"Bearer {token}", observation)]


class SlowReceiver:
    def __init__(self) -> None:
        self.started: asyncio.Event = asyncio.Event()
        self.closed: asyncio.Event = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self.receive(reader, writer))
        self._tasks.add(task)

    async def receive(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            fields = dict(line.split(": ", 1) for line in headers[1:] if ": " in line)
            await reader.readexactly(int(fields["Content-Length"]))
            writer.write(b"HTTP/1.1 204 No Content\r\nX-Slow: ")
            await writer.drain()
            self.started.set()
            while True:
                try:
                    if not await asyncio.wait_for(reader.read(1), timeout=0.05):
                        return
                except TimeoutError:
                    writer.write(b"x")
                    await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            self.closed.set()

    @asynccontextmanager
    async def publisher(self) -> AsyncGenerator[ObservationPublisher]:
        async with await asyncio.start_server(self.accept, "127.0.0.1", 0) as server:
            _, port = TypeAdapter(tuple[str, int]).validate_python(server.sockets[0].getsockname())
            publisher = ObservationPublisher(
                TelemetrySettings.model_validate(
                    {"receiver": f"http://127.0.0.1:{port}", "token": uuid4().hex}
                )
            )
            try:
                yield publisher
            finally:
                publisher.close()
                for task in self._tasks:
                    task.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)


def test_publisher_deadline_closes_a_response_that_keeps_dripping_headers() -> None:
    # Arrange
    async def scenario() -> bool:
        receiver = SlowReceiver()
        async with receiver.publisher() as publisher:
            observation = Observation(sampled_at=datetime.now(UTC), kind="host")
            # Act
            await asyncio.wait_for(publisher.publish(observation), timeout=3)
            await asyncio.wait_for(receiver.closed.wait(), timeout=1)
            return receiver.started.is_set()

    closed = asyncio.run(scenario())
    # Assert
    assert closed


@pytest.mark.parametrize("cancel", [True, False])
def test_publisher_shutdown_closes_the_inflight_connection(*, cancel: bool) -> None:
    # Arrange
    async def scenario() -> bool:
        receiver = SlowReceiver()
        async with receiver.publisher() as publisher:
            task = asyncio.create_task(
                publisher.publish(Observation(sampled_at=datetime.now(UTC), kind="host"))
            )
            await asyncio.wait_for(receiver.started.wait(), timeout=2)
            # Act
            if cancel:
                task.cancel()
            else:
                publisher.close()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1)
            await asyncio.wait_for(receiver.closed.wait(), timeout=1)
            return task.cancelled() if cancel else task.exception() is None

    closed = asyncio.run(scenario())
    # Assert
    assert closed


@pytest.mark.parametrize("suffix", ["\r\nInjected: value", " ", "\u2603"])
def test_telemetry_credentials_reject_header_injection_or_nonbearer_characters(suffix: str) -> None:
    # Arrange
    token = uuid4().hex + suffix
    # Act
    with pytest.raises(ValidationError) as failure:
        TelemetrySettings.model_validate({"receiver": "https://example.com", "token": token})
    # Assert
    assert failure.value.error_count() == 1
