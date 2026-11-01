from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..accounts.enums import RegistrationMode
from ..shared.broker import BrokerSettings


class WebSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    registration_mode: RegistrationMode = Field(
        default=RegistrationMode.INVITE_ONLY, description="How this instance admits accounts"
    )

    broker: BrokerSettings | None = Field(
        default=None,
        description="Broker the web queues jobs on and reads results from; without it, and "
        "without storage, uploads answer 503",
    )
    asr_broker_user: str | None = Field(
        default=None,
        description="Broker user the ASR worker publishes as; transcription results from any "
        "other user are rejected. The web's own broker user when unset",
    )
    notes_broker_user: str | None = Field(
        default=None,
        description="Broker user the notes worker publishes as; notes results from any other "
        "user are rejected. The web's own broker user when unset",
    )
