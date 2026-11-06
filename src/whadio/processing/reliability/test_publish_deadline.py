import asyncio
import logging
from datetime import timedelta
from unittest.mock import Mock

import pytest
from aio_pika.abc import AbstractChannel, AbstractMessage
from pydantic import SecretStr

from conftest import refused_fields

from ...shared.broker import BrokerSettings, MessagePublisher, connect
from ..consumer import serve_publishing

LONG_ENOUGH_TO_NOTICE_A_HANG = 2


class SilentExchange:
    """A broker that blocks its publishers: only the publish after `silent_for` returns."""

    def __init__(self, silent_for: int) -> None:
        self.silent_for: int = silent_for
        self.confirmed: asyncio.Event = asyncio.Event()

    async def publish(
        self, _message: AbstractMessage, *, routing_key: str, mandatory: bool
    ) -> None:
        del routing_key, mandatory
        if self.silent_for:
            self.silent_for -= 1
            await asyncio.Event().wait()
        self.confirmed.set()


class OneJob:
    """Publishes one job; a failed publish leaves it for the next round, as the rollback does."""

    def __init__(self, publisher: MessagePublisher) -> None:
        self._publisher: MessagePublisher = publisher
        self._published: bool = False

    async def publish_next(self) -> bool:
        if self._published:
            return False
        await self._publisher.publish("jobs", b"{}", message_type="job", correlation_id="j1")
        self._published = True
        return True


async def serve_until_confirmed(exchange: SilentExchange) -> None:
    channel = Mock(spec=AbstractChannel, default_exchange=exchange)
    publisher = MessagePublisher(channel, None, timeout=timedelta(milliseconds=10))
    queued, stop = asyncio.Event(), asyncio.Event()
    serving = asyncio.create_task(
        serve_publishing(OneJob(publisher), queued, stop, timedelta(milliseconds=1))
    )
    try:
        async with asyncio.timeout(LONG_ENOUGH_TO_NOTICE_A_HANG):
            await exchange.confirmed.wait()
    finally:
        stop.set()
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)


async def connect_to_a_broker_that_never_answers() -> tuple[bool, int]:
    """Returns whether `connect` timed out, and how many tasks it left running."""
    # A stream writer nothing refers to closes its socket, which is a refusal and not a silence.
    silent_clients: list[asyncio.StreamWriter] = []

    def accept_and_stay_silent(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        silent_clients.append(writer)

    server = await asyncio.start_server(accept_and_stay_silent, "127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    settings = BrokerSettings(
        url=SecretStr(f"amqp://whadio:p@{address}/whadio?fail_fast=0"),
        timeout=timedelta(milliseconds=10),
    )
    connecting = asyncio.create_task(connect(settings, name="test"))
    done, _ = await asyncio.wait({connecting}, timeout=LONG_ENOUGH_TO_NOTICE_A_HANG)
    left_running = len(asyncio.all_tasks() - {asyncio.current_task(), connecting})
    timed_out = connecting in done and isinstance(connecting.exception(), TimeoutError)
    connecting.cancel()
    await asyncio.gather(connecting, return_exceptions=True)
    server.close()
    server.close_clients()
    return timed_out, left_running


def test_publish_the_broker_never_confirms_is_logged_as_a_failed_round(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    exchange = SilentExchange(silent_for=1)

    # Act
    with caplog.at_level(logging.ERROR):
        asyncio.run(serve_until_confirmed(exchange))

    # Assert
    assert "Publishing a job failed; it is retried on the next round" in caplog.messages


def test_job_goes_out_once_a_silent_broker_answers_again() -> None:
    # Arrange
    exchange = SilentExchange(silent_for=3)

    # Act
    asyncio.run(serve_until_confirmed(exchange))

    # Assert
    assert exchange.confirmed.is_set()


def test_connect_ends_at_the_deadline_with_fail_fast_off_in_the_url() -> None:
    # Act
    timed_out, _ = asyncio.run(connect_to_a_broker_that_never_answers())

    # Assert
    assert timed_out


def test_connect_that_gave_up_leaves_no_retry_task_running() -> None:
    # Act
    _, left_running = asyncio.run(connect_to_a_broker_that_never_answers())

    # Assert
    assert left_running == 0


def test_broker_timeout_of_zero_is_refused() -> None:
    # Arrange
    data = {"url": "amqp://whadio:p@broker/whadio", "timeout": "PT0S"}

    # Act
    refused = refused_fields(BrokerSettings, data)

    # Assert
    assert refused == {"timeout"}
