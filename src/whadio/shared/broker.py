import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection, DeliveryMode
from pydantic import BaseModel, Field, SecretStr


class BrokerSettings(BaseModel):
    url: SecretStr = Field(
        description="AMQP URL with this runtime's own credentials and the vhost, "
        "such as amqp://whadio:password@localhost:5672/whadio"
    )
    timeout: timedelta = Field(
        default=timedelta(seconds=10),
        gt=timedelta(0),
        description="Time after which connecting to the broker, or a publish it does not confirm, "
        "is given up",
    )

    @property
    def user(self) -> str | None:
        return urlsplit(self.url.get_secret_value()).username


async def connect(settings: BrokerSettings, *, name: str) -> AbstractRobustConnection:
    # The timeout bounds one attempt. `fail_fast=0` in the URL would keep retrying past it in a
    # background task, so this argument overrides the URL and the first failed attempt raises.
    return await aio_pika.connect_robust(
        settings.url.get_secret_value(),
        timeout=settings.timeout.total_seconds(),
        fail_fast=True,
        client_properties={"connection_name": name},
    )


async def declare_queue(
    channel: AbstractChannel, name: str, arguments: Mapping[str, str | int]
) -> AbstractQueue:
    return await channel.declare_queue(name, durable=True, arguments=dict(arguments))


class MessagePublisher:
    def __init__(
        self, channel: AbstractChannel, user_id: str | None, *, timeout: timedelta
    ) -> None:
        self._channel: AbstractChannel = channel
        self._user_id: str | None = user_id
        self._timeout: timedelta = timeout

    async def publish(
        self, queue: str, body: bytes, *, message_id: UUID, message_type: str, correlation_id: str
    ) -> None:
        # RabbitMQ refuses a `user_id` other than the connection's user, so consumers can trust
        # it to name the runtime that published the message.
        message = aio_pika.Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id.hex,
            correlation_id=correlation_id,
            type=message_type,
            user_id=self._user_id,
            timestamp=datetime.now(UTC),
        )
        # aio-pika waits for the confirm without a limit by default, and a broker that blocks its
        # publishers (a memory or disk alarm) never sends one, while the caller may hold a row lock.
        # Its own `timeout` argument starts only after the wait for a reconnecting connection.
        async with asyncio.timeout(self._timeout.total_seconds()):
            await self._channel.default_exchange.publish(message, routing_key=queue, mandatory=True)
