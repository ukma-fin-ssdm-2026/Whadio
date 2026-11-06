import asyncio
import logging
from collections.abc import Coroutine
from datetime import timedelta
from unittest.mock import Mock

import pytest
from aio_pika.abc import AbstractChannel, AbstractMessage

from conftest import refused_fields

from ...shared.broker import BrokerSettings, MessagePublisher
from ..consumer import serve_publishing

LONG_ENOUGH_TO_NOTICE_A_HANG = 2


class SilentExchange:
    """A broker that blocks its publishers: the confirm comes only after `silent_for` publishes."""

    def __init__(self, silent_for: int) -> None:
        self.silent_for: int = silent_for
        self.confirmed: asyncio.Event = asyncio.Event()

    def publish(
        self,
        _message: AbstractMessage,
        *,
        routing_key: str,
        mandatory: bool,
        timeout: float | None,
    ) -> Coroutine[None, None, None]:
        del routing_key, mandatory
        return self._answer(timeout)

    async def _answer(self, limit: float | None) -> None:
        if self.silent_for:
            self.silent_for -= 1
            async with asyncio.timeout(limit):
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


def test_broker_timeout_of_zero_is_refused() -> None:
    # Arrange
    data = {"url": "amqp://whadio:p@broker/whadio", "timeout": "PT0S"}

    # Act
    refused = refused_fields(BrokerSettings, data)

    # Assert
    assert refused == {"timeout"}
