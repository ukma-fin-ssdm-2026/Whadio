from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..shared.broker import BrokerSettings


class WebSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    broker: BrokerSettings | None = Field(
        default=None,
        description="Broker the web queues jobs on and reads results from; without it, and "
        "without storage, uploads answer 503",
    )
    worker_broker_users: list[str] = Field(
        default_factory=list[str],
        description="Broker users the workers publish results as; a result from any other user "
        "is rejected. The web's own broker user when empty, for a broker that all share",
    )
