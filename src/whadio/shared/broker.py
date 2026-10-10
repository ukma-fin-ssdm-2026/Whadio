from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection, DeliveryMode
from pydantic import BaseModel, Field, SecretStr


class BrokerSettings(BaseModel):
    url: SecretStr = Field(
        description="AMQP URL with this runtime's own credentials and the vhost, "
        "such as amqp://whadio:password@localhost:5672/whadio"
    )

    @property
    def user(self) -> str | None:
        return urlsplit(self.url.get_secret_value()).username


async def connect(settings: BrokerSettings, *, name: str) -> AbstractRobustConnection:
    return await aio_pika.connect_robust(
        settings.url.get_secret_value(), client_properties={"connection_name": name}
    )


async def declare_queue(
    channel: AbstractChannel, name: str, arguments: Mapping[str, str | int]
) -> AbstractQueue:
    return await channel.declare_queue(name, durable=True, arguments=dict(arguments))


class MessagePublisher:
    def __init__(self, channel: AbstractChannel, user_id: str | None) -> None:
        self._channel: AbstractChannel = channel
        self._user_id: str | None = user_id

    async def publish(
        self, queue: str, body: bytes, *, message_type: str, correlation_id: str
    ) -> None:
        # RabbitMQ refuses a `user_id` other than the connection's user, so consumers can trust
        # it to name the runtime that published the message.
        message = aio_pika.Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=uuid4().hex,
            correlation_id=correlation_id,
            type=message_type,
            user_id=self._user_id,
            timestamp=datetime.now(UTC),
        )
        await self._channel.default_exchange.publish(message, routing_key=queue, mandatory=True)
