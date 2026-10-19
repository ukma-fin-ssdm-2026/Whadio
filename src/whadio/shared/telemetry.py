import asyncio
import logging
import re
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import ClassVar, Literal, Self

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class GpuObservation(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", allow_inf_nan=False)
    device: str = Field(pattern=r"^gpu-[0-9]{1,2}$", description="Opaque local GPU alias")
    utilization_percent: float = Field(
        ge=0, le=100, description="GPU utilization percent over driver sampling window"
    )
    memory_used_bytes: int = Field(ge=0, description="Used GPU memory in bytes")
    memory_total_bytes: int = Field(gt=0, description="Total GPU memory in bytes")

    @model_validator(mode="after")
    def within_capacity(self) -> Self:
        if self.memory_used_bytes > self.memory_total_bytes:
            raise ValueError("GPU memory usage exceeds capacity")
        return self


class Observation(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", allow_inf_nan=False)
    sampled_at: AwareDatetime = Field(description="UTC time of the source measurement")
    kind: Literal["host", "runtime"] = Field(description="Source measurement scope")
    cpu_percent: float | None = Field(
        default=None, ge=0, le=100, description="Host CPU busy percent normalized over logical CPUs"
    )
    logical_cpus: int | None = Field(default=None, ge=1, description="Host logical CPU count")
    memory_used_bytes: int | None = Field(
        default=None, ge=0, description="Host used memory bytes, excluding available memory"
    )
    memory_total_bytes: int | None = Field(
        default=None, gt=0, description="Host total memory bytes"
    )
    storage_used_bytes: int | None = Field(
        default=None, ge=0, description="Used bytes of the configured monitored volume"
    )
    storage_total_bytes: int | None = Field(
        default=None, gt=0, description="Total bytes of that same volume"
    )
    gpus: list[GpuObservation] | None = Field(
        default=None,
        max_length=16,
        description=(
            "GPU observations; null when unsupported/unavailable, empty if confirmed absent"
        ),
    )
    runtime: Literal["asr", "notes"] | None = Field(
        default=None, description="Runtime being measured"
    )
    availability: Literal["ready", "loading", "unavailable", "disabled", "unknown"] | None = Field(
        default=None, description="Runtime lifecycle state"
    )
    provider: Literal["local", "anthropic"] | None = Field(
        default=None, description="Actual execution provider, not workspace scaffold values"
    )
    credential_origin: Literal["deployment", "workspace", "none"] | None = Field(
        default=None, description="Credential ownership category without credential material"
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$",
        description="Configured model identifier, never a local file path",
    )
    active: int | None = Field(
        default=None, ge=0, description="Active slots/requests; null when unknown"
    )
    capacity: int | None = Field(
        default=None,
        ge=1,
        description="Configured slots/concurrency for this same runtime instance",
    )

    @field_validator("sampled_at")
    @classmethod
    def sample_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent_measurements(self) -> Self:
        host = (
            self.cpu_percent,
            self.logical_cpus,
            self.memory_used_bytes,
            self.memory_total_bytes,
            self.storage_used_bytes,
            self.storage_total_bytes,
            self.gpus,
        )
        runtime = (
            self.runtime,
            self.availability,
            self.provider,
            self.credential_origin,
            self.model,
            self.active,
            self.capacity,
        )
        if self.kind == "host" and any(value is not None for value in runtime):
            raise ValueError("A host source cannot publish runtime observations")
        if self.kind == "runtime" and (
            any(value is not None for value in host)
            or self.runtime is None
            or self.availability is None
        ):
            raise ValueError("A runtime source requires runtime identity and no host measurements")
        if self.runtime == "notes":
            origins = (None, "none") if self.provider == "local" else (None, "deployment")
            if self.credential_origin not in origins:
                raise ValueError("Notes credential origin must match the execution provider")
        if self.runtime == "asr" and (
            self.provider not in (None, "local") or self.credential_origin not in (None, "none")
        ):
            raise ValueError("ASR executes locally without a provider credential")
        for used, total in (
            (self.memory_used_bytes, self.memory_total_bytes),
            (self.storage_used_bytes, self.storage_total_bytes),
            (self.active, self.capacity),
        ):
            if used is not None and total is not None and used > total:
                raise ValueError("Usage exceeds capacity")
        return self


class TelemetrySettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_TELEMETRY_",
        env_ignore_empty=True,
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    receiver: AnyHttpUrl | None = Field(
        default=None,
        description="Private receiver origin; HTTP only on the encrypted private network",
    )
    source_id: str = Field(
        default="worker",
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
        description="Configured opaque source alias",
    )
    token: SecretStr | None = Field(
        default=None,
        min_length=32,
        description="Source-scoped collector bearer token from the environment",
    )
    interval_seconds: float = Field(
        default=10, ge=1, le=60, description="Observation publication interval"
    )

    @field_validator("token")
    @classmethod
    def bearer_token(cls, value: SecretStr | None) -> SecretStr | None:
        if (
            value is not None
            and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value.get_secret_value()) is None
        ):
            raise ValueError("Telemetry token must use bearer-token characters")
        return value

    @model_validator(mode="after")
    def credentials_together(self) -> Self:
        if (self.receiver is None) != (self.token is None):
            raise ValueError("Telemetry receiver and source token must be configured together")
        url = self.receiver
        if url is not None and (
            url.username is not None
            or url.password is not None
            or url.query is not None
            or url.fragment is not None
            or url.path not in (None, "/")
        ):
            raise ValueError("Receiver must be an origin without credentials or URL components")
        return self


def _response_status(headers: bytes) -> int:
    status = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: [^\r\n]*)?", headers.split(b"\r\n", 1)[0])
    if status is None:
        raise ValueError("Invalid telemetry response")
    return int(status[1])


class ObservationPublisher:
    def __init__(self, settings: TelemetrySettings) -> None:
        self._settings: TelemetrySettings = settings
        self._connections: set[asyncio.StreamWriter] = set()

    async def publish(self, observation: Observation) -> None:
        settings = self._settings
        receiver, token = settings.receiver, settings.token
        if receiver is None or token is None or receiver.host is None:
            return
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(2):
                reader, writer = await asyncio.open_connection(
                    receiver.host.strip("[]"),
                    receiver.port or (443 if receiver.scheme == "https" else 80),
                    ssl=ssl.create_default_context() if receiver.scheme == "https" else None,
                    limit=16384,
                )
                self._connections.add(writer)
                body = observation.model_dump_json().encode()
                host = str(receiver).removeprefix(f"{receiver.scheme}://").rstrip("/")
                writer.write(
                    (
                        f"POST /api/v1/admin/observations/{settings.source_id} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"Authorization: Bearer {token.get_secret_value()}\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    + body
                )
                await writer.drain()
                headers = await reader.readuntil(b"\r\n\r\n")
                if _response_status(headers) != HTTPStatus.NO_CONTENT:
                    logger.warning("Telemetry observation was not accepted")
        except (
            OSError,
            TimeoutError,
            ValueError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            logger.warning("Telemetry receiver unavailable")
        finally:
            if writer is not None:
                self._connections.discard(writer)
                # Abort also closes a TLS peer that refuses to finish its shutdown handshake.
                writer.transport.abort()

    def close(self) -> None:
        for writer in self._connections:
            writer.transport.abort()
        self._connections.clear()


RuntimeAvailability = Literal["ready", "loading", "unavailable", "disabled", "unknown"]


class RuntimeActivity:
    def __init__(
        self,
        runtime: Literal["asr", "notes"],
        capacity: int,
        model: str,
        *,
        availability: Callable[[], RuntimeAvailability] | None = None,
        provider: Literal["local", "anthropic"] | None = None,
    ) -> None:
        self.runtime: Literal["asr", "notes"] = runtime
        self.capacity: int = capacity
        self.model: str = model
        self.provider: Literal["local", "anthropic"] = provider or (
            "anthropic" if runtime == "notes" else "local"
        )
        self.active: int = 0
        self.ready: bool = False
        self._availability: Callable[[], RuntimeAvailability] | None = availability

    def observation(self) -> Observation:
        availability = (
            self._availability()
            if self._availability is not None
            else "ready"
            if self.ready
            else "loading"
        )
        return Observation(
            sampled_at=datetime.now(UTC),
            kind="runtime",
            runtime=self.runtime,
            availability=availability,
            provider=self.provider,
            credential_origin="deployment" if self.provider == "anthropic" else "none",
            model=self.model,
            active=self.active if availability == "ready" else None,
            capacity=self.capacity,
        )


async def publish_activity(
    activity: RuntimeActivity, settings: TelemetrySettings, stop: asyncio.Event
) -> None:
    publisher = ObservationPublisher(settings)
    try:
        while not stop.is_set():
            try:
                await publisher.publish(activity.observation())
            except ValidationError:
                logger.warning("Runtime telemetry observation invalid")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.interval_seconds)
            except TimeoutError:
                continue
    finally:
        publisher.close()
